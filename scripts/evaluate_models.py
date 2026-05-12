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

EVALUATION_TABLE = f"{HIVE_DB}.evaluation"
SWEEP_TABLE = f"{HIVE_DB}.eval_threshold_sweep"

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

    # 2. ML models — load + score.
    for name, path, cls, _ in MODELS:
        precision, recall, f1, pr_auc, alerts = score_model(spark, name, path, cls, test)
        print(f"[evaluate] {name}  P={precision:.4f}  R={recall:.4f}  "
              f"F1={f1:.4f}  PR-AUC={pr_auc:.4f}  alerts={alerts:,}")
        rows.append((name, precision, recall, f1, pr_auc, alerts))

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
    # -------------------------------------------------------------------------
    sweep_rows = []
    for name, _path, _cls, model_dir in MODELS:
        prob_path = f"project/output/{model_dir}_probabilities"
        print(f"[evaluate] reading probabilities for {name} from {prob_path}")
        probs = (spark.read
                 .option("header", "true")
                 .option("inferSchema", "true")
                 .csv(prob_path))
        model_sweep = threshold_sweep(probs, SWEEP_THRESHOLDS, name)
        for r in model_sweep:
            print(f"[evaluate]   thr={r[1]:.2f}  P={r[2]:.4f}  R={r[3]:.4f}  "
                  f"F1={r[4]:.4f}  alerts={r[5]:,}")
        sweep_rows.extend(model_sweep)

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

    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
