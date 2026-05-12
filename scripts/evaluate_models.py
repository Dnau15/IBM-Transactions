"""Stage III — model comparison + headline evaluation.csv.

Loads both saved Spark ML models, re-scores the held-out test split, and
emits a single evaluation table that places the rule baseline (single
operating point) and the two ML models (binarized at threshold=0.5) on
the same axes:

    model, precision, recall, f1, pr_auc, alert_volume

Outputs:
    HDFS  project/output/evaluation   one-partition CSV
    Hive  team1_projectdb.evaluation  external table over that CSV path
                                       (so Apache Superset / beeline can
                                       chart it during Stage IV)

Metrics rationale (ml.md §6):
    * minority-class F1 and PR-AUC are the primary numbers — accuracy
      and ROC-AUC are meaningless under 1:1000 class imbalance.
    * alert_volume = TP + FP — the headline business metric a compliance
      officer cares about (analyst hours per day per flagged txn).
    * The rule baseline produces a single 0/1 alert, so its PR-AUC slot
      is NaN-equivalent (full PR curve undefined for a single point).
"""
import sys

from pyspark.ml.classification import GBTClassificationModel, LogisticRegressionModel
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.sql import functions as F

from spark_session import HIVE_DB, build_session


HDFS_TEST = "project/data/test_parquet"
HDFS_EVAL = "project/output/evaluation"
HDFS_RULE_OUT = "project/output/rule_baseline"
# Threshold-sweep table: many rows per ML model, one per probability cutoff.
HDFS_SWEEP = "project/output/eval_threshold_sweep"
# Value-sweep table: per-currency dollar-recovery threshold sweep.
HDFS_VALUE_SWEEP = "project/output/eval_value_sweep"
# Diagnostic breakdown tables (Stage IV dashboard inputs).
HDFS_PATTERN_RECALL = "project/output/eval_pattern_recall"
HDFS_WEEKEND_WEEKDAY = "project/output/eval_weekend_weekday"
HDFS_FIXED_RECALL = "project/output/eval_at_fixed_recall"

EVALUATION_TABLE = f"{HIVE_DB}.evaluation"
SWEEP_TABLE = f"{HIVE_DB}.eval_threshold_sweep"
VALUE_SWEEP_TABLE = f"{HIVE_DB}.eval_value_sweep"
PATTERN_RECALL_TABLE = f"{HIVE_DB}.eval_pattern_recall"
WEEKEND_WEEKDAY_TABLE = f"{HIVE_DB}.eval_weekend_weekday"
FIXED_RECALL_TABLE = f"{HIVE_DB}.eval_at_fixed_recall"

# Currencies kept distinct in the value sweep; everything else folds into
# "Other". Matches the bucketing already applied during feature engineering
# in build_features.py so the report can cross-reference the two tables.
VALUE_TOP_CURRENCIES = {
    "US Dollar",
    "Euro",
    "Yuan",
    "Yen",
    "UK Pound",
    "Ruble",
    "Canadian Dollar",
    "Australian Dollar",
}

# Eight canonical AMLworld laundering pattern types, in longest-first order
# so the prefix match in `_canonical_pattern_col` does not let
# 'GATHER-SCATTER' be shadowed by 'SCATTER'. Mirrors the same list in
# scripts/eda_plot.py.
CANONICAL_PATTERNS = sorted([
    "FAN-IN", "FAN-OUT", "GATHER-SCATTER", "SCATTER-GATHER",
    "CYCLE", "RANDOM", "BIPARTITE", "STACK",
], key=len, reverse=True)

# Operating-point recall targets reported by `at_fixed_recall`. These are
# the points an FIU would normally consider when sizing analyst capacity.
FIXED_RECALL_TARGETS = [0.50, 0.70, 0.90]

MODELS = [
    ("model1_LogisticRegression", "project/models/model1", LogisticRegressionModel, "model1"),
    ("model2_GBTClassifier",      "project/models/model2", GBTClassificationModel,  "model2"),
]

# Probability cutoffs swept in evaluation. Default-threshold 0.5 is included
# so the sweep table aligns with the evaluation.csv operating point. Upper
# end (0.95) is where the high-precision, low-volume regime lives at this
# prevalence — useful for the "alert budget" discussion in the report.
SWEEP_THRESHOLDS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95]


def confusion(df, pred_col="prediction", label_col="label"):
    """Compute TP/FP/FN/TN -> precision/recall/F1 + alert_volume in one shuffle."""
    agg = df.agg(
        F.sum(((F.col(pred_col) == 1) & (F.col(label_col) == 1)).cast("long")).alias("tp"),
        F.sum(((F.col(pred_col) == 1) & (F.col(label_col) == 0)).cast("long")).alias("fp"),
        F.sum(((F.col(pred_col) == 0) & (F.col(label_col) == 1)).cast("long")).alias("fn"),
        F.sum(((F.col(pred_col) == 0) & (F.col(label_col) == 0)).cast("long")).alias("tn"),
    ).collect()[0]
    tp, fp, fn = agg["tp"], agg["fp"], agg["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1, (tp + fp)


def score_model(spark, name, model_path, model_cls, test):
    """Load a saved model, predict on test, return (precision, recall, f1, pr_auc, alerts)."""
    print(f"[evaluate] loading {name} from {model_path}")
    model = model_cls.load(model_path)

    predictions = model.transform(test)

    # PR-AUC over the full continuous score (rawPrediction).
    evaluator = BinaryClassificationEvaluator(
        labelCol="label",
        rawPredictionCol="rawPrediction",
        metricName="areaUnderPR",
    )
    pr_auc = evaluator.evaluate(predictions)

    # Binarized metrics at the model's default threshold (0.5).
    precision, recall, f1, alerts = confusion(predictions)
    return precision, recall, f1, pr_auc, alerts


def threshold_sweep(probabilities, thresholds, model_name):
    """Compute (precision, recall, f1, alerts) for many thresholds in a single scan.

    Reads from a (label, prediction, proba_positive) DataFrame written by
    train_models.py. For each threshold we sum tp/fp via boolean masks
    on `proba_positive`; total_pos = #positives is shared across thresholds.
    Returns a list of (model_name, threshold, precision, recall, f1, alerts).
    """
    # Build one aggregate per threshold + one global positive count.
    # `int(thr*100)` keys avoid float-in-column-name issues.
    agg_cols = []
    for thr in thresholds:
        key = int(thr * 100)
        agg_cols.append(
            F.sum(((F.col("proba_positive") >= thr) & (F.col("label") == 1)).cast("long"))
             .alias(f"tp_{key}")
        )
        agg_cols.append(
            F.sum(((F.col("proba_positive") >= thr) & (F.col("label") == 0)).cast("long"))
             .alias(f"fp_{key}")
        )
    agg_cols.append(
        F.sum((F.col("label") == 1).cast("long")).alias("pos_total")
    )

    res = probabilities.agg(*agg_cols).collect()[0]
    pos_total = int(res["pos_total"] or 0)

    rows = []
    for thr in thresholds:
        key = int(thr * 100)
        tp = int(res[f"tp_{key}"] or 0)
        fp = int(res[f"fp_{key}"] or 0)
        alerts = tp + fp
        precision = tp / alerts if alerts else 0.0
        recall = tp / pos_total if pos_total else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
        rows.append((model_name, float(thr), precision, recall, f1, alerts))
    return rows


def value_sweep(probabilities, thresholds, model_name):
    """Per-currency value-based threshold sweep.

    For every (currency_bucket, threshold) cell, compute:

        total_laundering_value   sum(amount_paid where label=1)
        detected_value           sum(amount_paid where label=1 and proba>=thr)
        false_positive_value     sum(amount_paid where label=0 and proba>=thr)
        value_recall             detected_value    / total_laundering_value
        value_precision          detected_value    / (detected_value + false_positive_value)
        alerts                   count(rows where proba>=thr)

    Currencies outside the top-8 are folded into "Other" (matches the
    feature-engineering bucket scope). All sums stay in the original
    currency — no FX conversion is performed, so each row's values are
    interpretable on their own without a synthetic exchange-rate
    assumption.

    Returns a list of
        (model_name, threshold, currency, total_laundering_value,
         detected_value, false_positive_value, value_recall,
         value_precision, alerts).
    """
    # Bucket currencies before aggregating.
    probs = probabilities.withColumn(
        "currency_bucket",
        F.when(F.col("payment_currency").isin(*VALUE_TOP_CURRENCIES),
               F.col("payment_currency"))
         .otherwise(F.lit("Other")),
    )

    # One scan per model, all thresholds inside.
    agg_cols = [
        F.sum(F.when(F.col("label") == 1, F.col("amount_paid")).otherwise(0.0))
            .alias("pos_value"),
    ]
    for thr in thresholds:
        key = int(thr * 100)
        agg_cols.append(
            F.sum(F.when(
                (F.col("proba_positive") >= thr) & (F.col("label") == 1),
                F.col("amount_paid"),
            ).otherwise(0.0)).alias(f"tp_val_{key}")
        )
        agg_cols.append(
            F.sum(F.when(
                (F.col("proba_positive") >= thr) & (F.col("label") == 0),
                F.col("amount_paid"),
            ).otherwise(0.0)).alias(f"fp_val_{key}")
        )
        agg_cols.append(
            F.sum((F.col("proba_positive") >= thr).cast("long"))
                .alias(f"alerts_{key}")
        )

    grouped = probs.groupBy("currency_bucket").agg(*agg_cols).collect()

    rows = []
    for row in grouped:
        currency = row["currency_bucket"]
        pos_value = float(row["pos_value"] or 0.0)
        for thr in thresholds:
            key = int(thr * 100)
            tp_val = float(row[f"tp_val_{key}"] or 0.0)
            fp_val = float(row[f"fp_val_{key}"] or 0.0)
            alerts = int(row[f"alerts_{key}"] or 0)
            value_recall = tp_val / pos_value if pos_value > 0 else 0.0
            denom = tp_val + fp_val
            value_precision = tp_val / denom if denom > 0 else 0.0
            rows.append((
                model_name, float(thr), currency, pos_value, tp_val,
                fp_val, value_recall, value_precision, alerts,
            ))
    return rows


def _canonical_pattern_col(col):
    """Map a `pattern_type` column to its 8-type canonical prefix.

    Mirrors `_canonicalize_pattern` in eda_plot.py but runs in-engine
    instead of on the driver, so the join+groupBy in `pattern_recall`
    stays distributed.

    The order of checks matters: longest canonical names first so
    'GATHER-SCATTER' is not shadowed by 'SCATTER' (which would be wrong
    because there is no 'SCATTER' canonical class -- 'SCATTER-GATHER' is).
    """
    expr = F.lit("OTHER")
    # Iterate longest-first; the resulting nested when() falls through to
    # the next pattern if the previous .otherwise() branch is taken.
    for canon in CANONICAL_PATTERNS:
        expr = (
            F.when(F.upper(col).startswith(canon), F.lit(canon))
             .otherwise(expr)
        )
    return expr


def pattern_recall(predictions, patterns_df, model_name):
    """Per-canonical-pattern recall on test-window laundering rows.

    Joins test predictions (laundering rows only) with the patterns
    table on (from_account, to_account, ts_unix) -- the natural
    transaction key. Groups by canonical pattern type and reports
    n_total / n_caught / recall, where n_caught counts rows with
    prediction=1 (i.e.\\ the default 0.5 threshold).

    `patterns_df` is expected to carry `from_account`, `to_account`,
    `ts_unix` (long seconds) and `canon_type` columns.
    """
    laundering_pred = predictions.filter(F.col("label") == 1)
    joined = laundering_pred.join(
        patterns_df,
        on=["from_account", "to_account", "ts_unix"],
        how="inner",
    )
    agg = (joined.groupBy("canon_type")
                 .agg(
                     F.count(F.lit(1)).alias("n_total"),
                     F.sum((F.col("prediction") == 1).cast("long"))
                       .alias("n_caught"),
                 )
                 .collect())
    rows = []
    for r in agg:
        n_total = int(r["n_total"] or 0)
        n_caught = int(r["n_caught"] or 0)
        recall = n_caught / n_total if n_total > 0 else 0.0
        rows.append((model_name, r["canon_type"], n_total, n_caught, recall))
    return rows


def weekend_weekday_breakdown(predictions, model_name):
    """Recall on laundering rows split by `is_weekend` (the binary flag in
    DIAGNOSTIC_COLS, motivated by the q12 weekend-midday laundering peak).

    Returns one row per (model, segment), segment in {'weekday', 'weekend'},
    with n_positives / n_caught / recall computed at the model's default
    threshold (prediction column).
    """
    agg = (predictions
           .filter(F.col("label") == 1)
           .groupBy("is_weekend")
           .agg(
               F.count(F.lit(1)).alias("n_positives"),
               F.sum((F.col("prediction") == 1).cast("long"))
                 .alias("n_caught"),
           )
           .collect())
    rows = []
    for r in agg:
        segment = "weekend" if int(r["is_weekend"]) == 1 else "weekday"
        n_pos = int(r["n_positives"] or 0)
        n_caught = int(r["n_caught"] or 0)
        recall = n_caught / n_pos if n_pos > 0 else 0.0
        rows.append((model_name, segment, n_pos, n_caught, recall))
    return rows


def at_fixed_recall(probabilities, target_recalls, model_name):
    """For each target recall, find the smallest threshold whose actual
    test-set recall meets or exceeds the target, and report the resulting
    alert volume + precision.

    Approach: collect only the positives (~tens of thousands of rows at
    HI-Medium scale) to the driver, sort by `proba_positive` descending,
    and pick the row whose 1-indexed rank equals ceil(target * n_pos).
    That row's probability is the threshold to use; we then count alerts
    and true positives on the full probabilities table.

    Collecting positives to the driver is safe here -- the count is bounded
    by the laundering-rate (~1:1021 * test size), which is in the low
    tens of thousands even on HI-Medium.
    """
    import math

    pos_pdf = (probabilities
               .filter(F.col("label") == 1)
               .select("proba_positive")
               .toPandas()
               .sort_values("proba_positive", ascending=False)
               .reset_index(drop=True))
    n_pos = len(pos_pdf)

    if n_pos == 0:
        return [
            (model_name, float(t), 0.0, 0, 0, 0.0, 0.0)
            for t in target_recalls
        ]

    rows = []
    for target in target_recalls:
        # Smallest k such that k / n_pos >= target.
        k = max(1, math.ceil(target * n_pos))
        k = min(k, n_pos)
        threshold = float(pos_pdf.iloc[k - 1]["proba_positive"])
        # Count all alerts and true positives at this threshold.
        stats = (probabilities.agg(
            F.sum((F.col("proba_positive") >= threshold).cast("long"))
              .alias("alerts"),
            F.sum(((F.col("proba_positive") >= threshold) & (F.col("label") == 1))
                  .cast("long")).alias("tp"),
        ).collect()[0])
        alerts = int(stats["alerts"] or 0)
        tp = int(stats["tp"] or 0)
        actual_recall = tp / n_pos if n_pos > 0 else 0.0
        precision = tp / alerts if alerts > 0 else 0.0
        rows.append((
            model_name, float(target), threshold, alerts, tp,
            actual_recall, precision,
        ))
    return rows


def main():
    spark = build_session("evaluate_models")

    test = spark.read.parquet(HDFS_TEST)
    print(f"[evaluate] test rows = {test.count():,}  "
          f"positives = {test.filter(F.col('label') == 1).count():,}")

    rows = []

    # 1. Rule baseline — read the row already produced by rule_baseline.py.
    print(f"[evaluate] loading rule baseline from {HDFS_RULE_OUT}")
    rule = (spark.read
            .option("header", "true")
            .option("inferSchema", "true")
            .csv(HDFS_RULE_OUT)
            .collect()[0])
    rows.append((
        rule["model"],
        float(rule["precision"]),
        float(rule["recall"]),
        float(rule["f1"]),
        float("nan"),  # PR-AUC undefined for a binary rule.
        int(rule["alert_volume"]),
    ))

    # 2. ML models — load each model once and run the headline metrics,
    #    the weekend/weekday breakdown, and the pattern-recall breakdown
    #    against the same cached predictions DataFrame. Loading + scoring
    #    test is the expensive part; caching avoids paying it three times.
    print(f"[evaluate] preparing patterns table for pattern-recall join")
    patterns_df = (
        spark.table(f"{HIVE_DB}.laundering_patterns")
             .select(
                 F.col("from_account"),
                 F.col("to_account"),
                 F.col("ts").cast("long").alias("ts_unix"),
                 F.col("pattern_type"),
             )
             .withColumn("canon_type",
                         _canonical_pattern_col(F.col("pattern_type")))
    )

    ww_rows = []
    pr_rows = []
    binary_evaluator = BinaryClassificationEvaluator(
        labelCol="label",
        rawPredictionCol="rawPrediction",
        metricName="areaUnderPR",
    )
    for name, path, cls, _ in MODELS:
        print(f"[evaluate] loading {name} from {path}")
        model = cls.load(path)
        # Score once; project to the columns the four downstream calls need.
        predictions = (
            model.transform(test)
                 .select(
                     "label", "prediction", "probability", "rawPrediction",
                     "is_weekend",
                     "from_account", "to_account", "ts_unix",
                 )
                 .cache()
        )

        pr_auc = binary_evaluator.evaluate(predictions)
        precision, recall, f1, alerts = confusion(predictions)
        print(f"[evaluate] {name}  P={precision:.4f}  R={recall:.4f}  "
              f"F1={f1:.4f}  PR-AUC={pr_auc:.4f}  alerts={alerts:,}")
        rows.append((name, precision, recall, f1, pr_auc, alerts))

        # Weekend/weekday recall breakdown.
        for r in weekend_weekday_breakdown(predictions, name):
            print(f"[evaluate]   ww/{r[1]:<8s} n_pos={r[2]:,}  "
                  f"n_caught={r[3]:,}  recall={r[4]:.4f}")
            ww_rows.append(r)

        # Per-canonical-pattern recall.
        for r in pattern_recall(predictions, patterns_df, name):
            print(f"[evaluate]   pat/{r[1]:<14s} n_total={r[2]:,}  "
                  f"n_caught={r[3]:,}  recall={r[4]:.4f}")
            pr_rows.append(r)

        predictions.unpersist()

    # 3. Write evaluation.csv.
    out = spark.createDataFrame(
        rows,
        schema="model string, precision double, recall double, f1 double, "
               "pr_auc double, alert_volume long",
    )

    print(f"[evaluate] writing -> {HDFS_EVAL}")
    (out.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(HDFS_EVAL))

    # 4. Hive external table — lets Superset chart the evaluation in Stage IV.
    spark.sql(f"DROP TABLE IF EXISTS {EVALUATION_TABLE}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {EVALUATION_TABLE} (
                model        STRING,
                precision    DOUBLE,
                recall       DOUBLE,
                f1           DOUBLE,
                pr_auc       DOUBLE,
                alert_volume BIGINT
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{HDFS_EVAL}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    # Print the final table so the stage3.sh log shows it explicitly.
    print("[evaluate] final comparison:")
    out.show(truncate=False)

    # -------------------------------------------------------------------------
    # 5. Threshold sweep — read each ML model's probabilities table (written
    #    by train_models.py step 9) and compute (precision, recall, f1, alerts)
    #    at multiple cutoffs in a single scan per model. This gives the report
    #    the operating-point curve that the rule baseline can't produce.
    #    The same probabilities table is reused for the value sweep in step 6,
    #    so we cache it once and unpersist after both sweeps run.
    # -------------------------------------------------------------------------
    sweep_rows = []
    value_sweep_rows = []
    fixed_recall_rows = []
    for name, _path, _cls, model_dir in MODELS:
        prob_path = f"project/output/{model_dir}_probabilities"
        print(f"[evaluate] reading probabilities for {name} from {prob_path}")
        probs = (spark.read
                 .option("header", "true")
                 .option("inferSchema", "true")
                 .csv(prob_path)
                 .cache())
        model_sweep = threshold_sweep(probs, SWEEP_THRESHOLDS, name)
        for r in model_sweep:
            print(f"[evaluate]   thr={r[1]:.2f}  P={r[2]:.4f}  R={r[3]:.4f}  "
                  f"F1={r[4]:.4f}  alerts={r[5]:,}")
        sweep_rows.extend(model_sweep)

        # Value sweep on the same cached probabilities.
        model_value = value_sweep(probs, SWEEP_THRESHOLDS, name)
        for r in model_value:
            print(f"[evaluate]   val/{r[2]:<18s} thr={r[1]:.2f}  "
                  f"vR={r[6]:.4f}  vP={r[7]:.4f}  "
                  f"detected={r[4]:,.0f}  alerts={r[8]:,}")
        value_sweep_rows.extend(model_value)

        # Fixed-recall operating points (same cached probabilities).
        model_fixed = at_fixed_recall(probs, FIXED_RECALL_TARGETS, name)
        for r in model_fixed:
            print(f"[evaluate]   fixedR={r[1]:.2f}  thr={r[2]:.4f}  "
                  f"alerts={r[3]:,}  tp={r[4]:,}  "
                  f"actualR={r[5]:.4f}  P={r[6]:.4f}")
        fixed_recall_rows.extend(model_fixed)

        probs.unpersist()

    sweep = spark.createDataFrame(
        sweep_rows,
        schema="model string, threshold double, precision double, recall double, "
               "f1 double, alert_volume long",
    )
    print(f"[evaluate] writing threshold sweep -> {HDFS_SWEEP}")
    (sweep.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(HDFS_SWEEP))

    # Hive external table for the sweep — also chartable in Superset.
    spark.sql(f"DROP TABLE IF EXISTS {SWEEP_TABLE}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {SWEEP_TABLE} (
                model        STRING,
                threshold    DOUBLE,
                precision    DOUBLE,
                recall       DOUBLE,
                f1           DOUBLE,
                alert_volume BIGINT
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{HDFS_SWEEP}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    # -------------------------------------------------------------------------
    # 6. Value sweep — per-currency dollar-recovery curve. Same threshold
    #    grid as the count sweep, but the question is "what fraction of
    #    laundered value is recovered" rather than "what fraction of
    #    laundering rows is recovered". Tuning the production threshold on
    #    value_recall vs alert volume is more decision-relevant for the FIU
    #    than tuning on count-recall.
    # -------------------------------------------------------------------------
    value_sweep_df = spark.createDataFrame(
        value_sweep_rows,
        schema="model string, threshold double, currency string, "
               "total_laundering_value double, detected_value double, "
               "false_positive_value double, value_recall double, "
               "value_precision double, alerts long",
    )
    print(f"[evaluate] writing value sweep -> {HDFS_VALUE_SWEEP}")
    (value_sweep_df.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(HDFS_VALUE_SWEEP))

    spark.sql(f"DROP TABLE IF EXISTS {VALUE_SWEEP_TABLE}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {VALUE_SWEEP_TABLE} (
                model                  STRING,
                threshold              DOUBLE,
                currency               STRING,
                total_laundering_value DOUBLE,
                detected_value         DOUBLE,
                false_positive_value   DOUBLE,
                value_recall           DOUBLE,
                value_precision        DOUBLE,
                alerts                 BIGINT
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{HDFS_VALUE_SWEEP}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    # -------------------------------------------------------------------------
    # 7. Pattern recall — per-canonical-pattern recall computed earlier in
    #    the model loop. One row per (model, canon_type).
    # -------------------------------------------------------------------------
    pr_df = spark.createDataFrame(
        pr_rows,
        schema="model string, canon_type string, n_total long, "
               "n_caught long, recall double",
    )
    print(f"[evaluate] writing pattern recall -> {HDFS_PATTERN_RECALL}")
    (pr_df.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(HDFS_PATTERN_RECALL))
    spark.sql(f"DROP TABLE IF EXISTS {PATTERN_RECALL_TABLE}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {PATTERN_RECALL_TABLE} (
                model      STRING,
                canon_type STRING,
                n_total    BIGINT,
                n_caught   BIGINT,
                recall     DOUBLE
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{HDFS_PATTERN_RECALL}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    # -------------------------------------------------------------------------
    # 8. Weekend / weekday breakdown — recall on laundering rows split by
    #    the `is_weekend` flag. Two rows per model.
    # -------------------------------------------------------------------------
    ww_df = spark.createDataFrame(
        ww_rows,
        schema="model string, segment string, n_positives long, "
               "n_caught long, recall double",
    )
    print(f"[evaluate] writing weekend/weekday -> {HDFS_WEEKEND_WEEKDAY}")
    (ww_df.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(HDFS_WEEKEND_WEEKDAY))
    spark.sql(f"DROP TABLE IF EXISTS {WEEKEND_WEEKDAY_TABLE}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {WEEKEND_WEEKDAY_TABLE} (
                model       STRING,
                segment     STRING,
                n_positives BIGINT,
                n_caught    BIGINT,
                recall      DOUBLE
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{HDFS_WEEKEND_WEEKDAY}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    # -------------------------------------------------------------------------
    # 9. Fixed-recall operating points — for each target recall, the
    #    smallest threshold meeting it, plus the resulting alert volume
    #    and precision. One row per (model, target_recall).
    # -------------------------------------------------------------------------
    fr_df = spark.createDataFrame(
        fixed_recall_rows,
        schema="model string, target_recall double, threshold double, "
               "alerts long, tp long, actual_recall double, precision double",
    )
    print(f"[evaluate] writing fixed-recall table -> {HDFS_FIXED_RECALL}")
    (fr_df.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(HDFS_FIXED_RECALL))
    spark.sql(f"DROP TABLE IF EXISTS {FIXED_RECALL_TABLE}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {FIXED_RECALL_TABLE} (
                model         STRING,
                target_recall DOUBLE,
                threshold     DOUBLE,
                alerts        BIGINT,
                tp            BIGINT,
                actual_recall DOUBLE,
                precision     DOUBLE
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{HDFS_FIXED_RECALL}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
