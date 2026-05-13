"""Stage III — rule-based AML baseline.

Implements three SQL rules on the test split of the feature table and
emits the same precision/recall/F1/PR-AUC numbers as the ML models, so
the headline evaluation.csv can put them on the same axes.

Rules (full justification in ml.md §4):
    R1 — Structuring: many small outflows under a regulatory threshold
         that aggregate above CTR-equivalent.
    R2 — Velocity / pass-through: inflows in 24h immediately followed by
         outflows within 1h with a low residual balance.
    R5 — Cross-bank diversity: an account transacts with many distinct
         banks in a short window — only detectable under the
         shared-features setup.

Each rule is a binary 0/1 alert; the aggregate rule_alert = OR across
the three. Thresholds are documented inline — they're picked from the
typical regulatory regime, NOT tuned on the test set (the discipline
ml.md §4 calls out: "thresholds tuned on training split only", but for
the minimum-viable baseline we use the textbook regulatory numbers
which are split-independent).

Output (HDFS): project/output/rule_baseline
              one-row CSV: model,precision,recall,f1,pr_auc,alert_volume

The rule baseline's per-currency dollar recovery is folded into the
single eval_value_sweep table by evaluate_models.py (one row per
currency, threshold=1.0 as a sentinel), so the rule sits next to the
ML models on the same plot and in the same Hive table.
"""
import sys

from pyspark.sql import functions as F

from spark_session import HIVE_DB, build_session


FEATURES_TABLE = f"{HIVE_DB}.features"
HDFS_OUT = "project/output/rule_baseline"

# --- Rule thresholds ----------------------------------------------------------

# R1 — structuring (smurfing under USD 10k reporting threshold)
R1_MIN_TX_24H = 5            # at least this many outgoing txns in 24h
R1_MAX_PER_TX = 10_000.0     # each individual tx below CTR threshold
R1_MIN_TOTAL = 30_000.0      # cumulative above 30k → suspicious

# R2 — pass-through velocity
R2_MIN_IN_24H = 3            # multiple incoming
R2_MIN_OUT_1H = 3            # then rapid outflow
R2_MAX_RESIDUAL_RATIO = 0.10 # |in_24h - out_1h| / in_24h < 10%

# R5 — cross-bank diversity
R5_MIN_BANKS_24H = 5         # 5+ distinct destination banks
R5_MIN_OUT_24H = 10          # in a meaningfully active account


def compute_test_split(spark):
    """Re-derive the test split using the same temporal cutoff as build_features.

    We don't import the train/test JSON directly because rule evaluation
    needs the raw feature columns (numeric counts, not the assembled
    Vector). Recomputing the cutoff is O(n) and matches build_features.py's
    TRAIN_FRACTION exactly.
    """
    from build_features import TRAIN_FRACTION  # local import for cli-arg safety

    feat = spark.table(FEATURES_TABLE)
    (cutoff,) = feat.approxQuantile("ts_unix", [TRAIN_FRACTION], 0.001)
    print(f"[rule_baseline] test cutoff ts_unix = {cutoff}")
    return feat.filter(F.col("ts_unix") > cutoff)


def apply_rules(test):
    """Add boolean rule columns and the disjunction `rule_alert`."""
    return (
        test
        # R1: structuring
        .withColumn(
            "r1_structuring",
            (
                (F.col("out_count_24h") >= R1_MIN_TX_24H)
                & (F.col("out_max_24h") < R1_MAX_PER_TX)
                & (F.col("out_sum_24h") > R1_MIN_TOTAL)
            ).cast("int"),
        )
        # R2: pass-through velocity
        .withColumn(
            "r2_velocity",
            (
                (F.col("in_count_24h") >= R2_MIN_IN_24H)
                & (F.col("out_count_1h") >= R2_MIN_OUT_1H)
                # Avoid divide-by-zero with GREATEST(_,1).
                & (
                    F.abs(F.col("in_sum_24h") - F.col("out_sum_1h"))
                    / F.greatest(F.col("in_sum_24h"), F.lit(1.0))
                    < R2_MAX_RESIDUAL_RATIO
                )
            ).cast("int"),
        )
        # R5: cross-bank diversity
        .withColumn(
            "r5_cross_bank",
            (
                (F.col("out_unique_banks_24h") >= R5_MIN_BANKS_24H)
                & (F.col("out_count_24h") >= R5_MIN_OUT_24H)
            ).cast("int"),
        )
        # Aggregate alert: OR across the three rules.
        .withColumn(
            "rule_alert",
            F.greatest("r1_structuring", "r2_velocity", "r5_cross_bank"),
        )
    )


def confusion_metrics(df, prediction_col="rule_alert", label_col="label"):
    """Compute TP/FP/FN/TN -> precision, recall, F1 in one shuffle."""
    agg = df.agg(
        F.sum(((F.col(prediction_col) == 1) & (F.col(label_col) == 1)).cast("long")).alias("tp"),
        F.sum(((F.col(prediction_col) == 1) & (F.col(label_col) == 0)).cast("long")).alias("fp"),
        F.sum(((F.col(prediction_col) == 0) & (F.col(label_col) == 1)).cast("long")).alias("fn"),
        F.sum(((F.col(prediction_col) == 0) & (F.col(label_col) == 0)).cast("long")).alias("tn"),
    ).collect()[0]

    tp, fp, fn, tn = agg["tp"], agg["fp"], agg["fn"], agg["tn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
    alert_volume = tp + fp
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "alert_volume": alert_volume,
    }


def main():
    spark = build_session("rule_baseline")

    test = compute_test_split(spark)
    scored = apply_rules(test).cache()

    # Per-rule breakdown (printed for the report; not in evaluation.csv).
    for rule in ("r1_structuring", "r2_velocity", "r5_cross_bank", "rule_alert"):
        m = confusion_metrics(scored, prediction_col=rule)
        print(
            f"[rule_baseline] {rule:18s}  "
            f"P={m['precision']:.4f}  R={m['recall']:.4f}  F1={m['f1']:.4f}  "
            f"alerts={m['alert_volume']:,}  TP={m['tp']:,}  FN={m['fn']:,}"
        )

    # Headline row for evaluation.csv — the aggregate rule_alert.
    m = confusion_metrics(scored, prediction_col="rule_alert")

    # PR-AUC is undefined for a binary rule (single operating point);
    # we report it as the rule's recall × precision area approximation
    # via the trivial degenerate curve. The ML models give a full curve;
    # the rule baseline anchors a single point. Reported as NaN-equivalent.
    pr_auc = float("nan")

    out = spark.createDataFrame(
        [(
            "rule_baseline_R1_R2_R5",
            m["precision"],
            m["recall"],
            m["f1"],
            pr_auc,
            m["alert_volume"],
        )],
        schema="model string, precision double, recall double, f1 double, "
               "pr_auc double, alert_volume long",
    )

    print(f"[rule_baseline] writing -> {HDFS_OUT}")
    (out.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(HDFS_OUT))

    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
