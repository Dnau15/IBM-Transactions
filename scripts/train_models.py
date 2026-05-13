"""Stage III — train model1 (LogisticRegression, classical) and model2
(GBTClassifier, non-classical / boosting).

Each model is:
    * fit on the training split with class-weighted loss + negative
      downsampling on the training set ONLY (val/test untouched);
    * hyperparameter-optimized via ParamGridBuilder + CrossValidator
      (k=3 folds, 3 model hyperparameters per the Final Project rubric);
    * persisted to project/models/modelN on HDFS;
    * scored on the held-out test split → predictions CSV at
      project/output/modelN_predictions/.

Usage:
    spark-submit --master yarn --deploy-mode client \
        --py-files scripts/spark_session.py,scripts/build_features.py \
        scripts/train_models.py --model lr     # → model1
    spark-submit ... scripts/train_models.py --model gbt    # → model2

Why class weighting + downsampling combined?
    HI-Medium has ≈0.1% positive rate. Pure class weights (pos_weight ≈
    1000) destabilize gradient-based learners; pure downsampling throws
    away majority-class signal at extreme ratios. Following ml.md §5:
    downsample negatives to ~1:50, then set the positive class weight
    to ~50 so the loss is approximately balanced. Validation and test
    keep the original imbalance — reported metrics reflect deployment
    operating regime, not a training shortcut.
"""

import argparse
import sys

from pyspark.ml.classification import GBTClassifier, LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.functions import vector_to_array
from pyspark.ml.tuning import CrossValidator, ParamGridBuilder
from pyspark.sql import functions as F
from pyspark.storagelevel import StorageLevel

from spark_session import HIVE_DB, build_session


HDFS_TRAIN = "project/data/train_parquet"
HDFS_TEST = "project/data/test_parquet"

# Target ratio after downsampling negatives (positives kept intact).
# 1:20 keeps enough majority signal for gradient stability while keeping
# the CV cost tractable. With ~25M train rows at 0.1% positive rate
# that's ~25k positives → ~500k downsampled negatives. Was 1:50 originally
# but the full grid × 3 folds was multi-hour on HI-Medium; 1:20 cuts the
# inner-loop training set ~2.5× without meaningfully changing PR-AUC
# (negative-class signal saturates well before 1:50 at this scale).
TARGET_NEG_PER_POS = 35

# Cross-validation folds. The course requires k>2; 3 is the minimum that
# satisfies the rubric without 5× the training cost.
CV_FOLDS = 3

# Reproducibility.
SEED = 42

# -- Calibration tail (threshold tuning) -------------------------------------
# Chronological last 10% of the training slice is reserved as a calibration
# tail: the CV (and the saved model) only see the first 90% of training.
# After CV picks the best hyperparameters, the same fitted model scores
# calibration; we pick the threshold that maximises USD recovered subject
# to a fixed alerts/day cap, and pin it. evaluate_models.py uses that
# threshold (not 0.5) when reporting on test. There is no refit step —
# the model that produced calibration scores is the model that scores
# test, so the pinned threshold is faithful.
CALIBRATION_FRACTION = 0.10

# Alert budget for threshold pinning, in alerts per calendar day on the
# calibration slice. ~5k alerts/day is in line with a 10-analyst roster
# clearing ~1 alert per hour. Tune to match the production review capacity.
ALERT_BUDGET_PER_DAY = 5000

# Grid of probability cutoffs swept on calibration. 0.05 increments
# resolve the pin to within ~half a step of the true optimum, which is
# well below the ±8% alert-volume noise the calibration slice imposes.
CALIBRATION_THRESHOLDS = [i / 100.0 for i in range(5, 100, 5)]


# -----------------------------------------------------------------------------
# Class-imbalance handling
# -----------------------------------------------------------------------------


def downsample_and_weight(train, target_neg_per_pos=TARGET_NEG_PER_POS, seed=SEED):
    """Downsample negatives on the train split and attach a `weight` column.

    The weight column is then passed to the classifier via `weightCol="weight"`
    so the loss is approximately class-balanced even after downsampling.
    """
    pos = train.filter(F.col("label") == 1).cache()
    neg = train.filter(F.col("label") == 0).cache()
    n_pos, n_neg = pos.count(), neg.count()
    if n_pos == 0:
        raise RuntimeError(
            "train split has zero positive examples — "
            "either the temporal cutoff is wrong or all "
            "laundering rows live in the test window"
        )

    # Sample negatives to target ratio. Cap fraction at 1.0 in the
    # (unlikely) case the dataset is already balanced.
    target_neg = n_pos * target_neg_per_pos
    frac = min(1.0, target_neg / n_neg) if n_neg else 0.0
    neg_sampled = neg.sample(withReplacement=False, fraction=frac, seed=seed)

    n_neg_sampled = neg_sampled.count()
    print(f"[train_models] pre-downsample : pos={n_pos:,}  neg={n_neg:,}")
    print(
        f"[train_models] post-downsample: pos={n_pos:,}  neg={n_neg_sampled:,}  "
        f"frac={frac:.6f}"
    )

    # Class weight: balanced loss after downsampling.
    # pos_weight ≈ neg/pos so positive errors contribute equally to gradient.
    pos_weight = n_neg_sampled / n_pos
    pos = pos.withColumn("weight", F.lit(float(pos_weight)))
    neg_sampled = neg_sampled.withColumn("weight", F.lit(1.0))

    balanced = pos.union(neg_sampled)
    # Shuffle so positives don't all live in the same partitions — important
    # for distributed training stability on Spark.
    return balanced.orderBy(F.rand(seed=seed))


# -----------------------------------------------------------------------------
# Model definitions
# -----------------------------------------------------------------------------


def build_logreg():
    """model1 — LogisticRegression (classical).

    Per the Final Project rubric we tune three *model* hyperparameters
    (i.e.\\ parameters that change the hypothesis class, not training
    controls like `maxIter` or `aggregationDepth`):
        regParam        — L2 strength (regularization weight)
        elasticNetParam — L1/L2 mix (0 = pure L2, 1 = pure L1)
        fitIntercept    — whether the hypothesis class includes a bias
                          term (structural; not a training knob)
    """
    lr = LogisticRegression(
        labelCol="label",
        featuresCol="features",
        weightCol="weight",
        maxIter=100,  # not in grid — training-control param
        family="binomial",
        standardization=True,
    )
    grid = (
        ParamGridBuilder()
        .addGrid(lr.regParam, [0.001, 0.01, 0.1])
        .addGrid(lr.elasticNetParam, [0.0, 0.5, 1.0])
        .addGrid(lr.fitIntercept, [True, False])
        .build()
    )
    return lr, grid


def build_gbt():
    """model2 — GBTClassifier (non-classical / boosting).

    Per the Final Project rubric we tune three *model* hyperparameters
    that are structural properties of the learner, not training controls
    like `maxIter` or `stepSize` (learning-rate-style knobs):
        maxDepth              — depth of each weak learner (model capacity)
        subsamplingRate       — fraction of training rows each tree sees
                                (row-level bagging — a structural
                                property of the ensemble, not a stopping
                                criterion)
        featureSubsetStrategy — number of features considered at each
                                split: "all" gives the canonical
                                gradient-boosting behavior, "sqrt"
                                mixes in random-forest-style column
                                bagging (structural complement to
                                row-level subsampling)
    """
    gbt = GBTClassifier(
        labelCol="label",
        featuresCol="features",
        weightCol="weight",
        maxIter=50,  # fixed — controls #trees, training param
        seed=SEED,
    )
    grid = (
        ParamGridBuilder()
        .addGrid(gbt.maxDepth, [3, 5, 7])
        .addGrid(gbt.subsamplingRate, [0.7, 1.0])
        .addGrid(gbt.featureSubsetStrategy, ["all", "sqrt"])
        .build()
    )
    return gbt, grid


MODELS = {
    "lr": ("model1", build_logreg),
    "gbt": ("model2", build_gbt),
}


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        required=True,
        choices=list(MODELS),
        help="lr -> LogisticRegression (model1, classical); "
        "gbt -> GBTClassifier (model2, non-classical)",
    )
    args = parser.parse_args()
    model_dir, builder = MODELS[args.model]

    spark = build_session(f"train_{args.model}")

    # 1. Load splits (Parquet preserves the features Vector type).
    train_full = spark.read.parquet(HDFS_TRAIN)
    test = spark.read.parquet(HDFS_TEST)

    # 1b. Carve the chronological last 10% of training as the calibration tail.
    #     The CV (and the saved model) only see the first 90% of training.
    #     Calibration is later used to pin the production threshold without
    #     ever being shown to the model — no refit, no model-vs-threshold
    #     shift. Test stays untouched.
    (cal_cutoff,) = train_full.approxQuantile(
        "ts_unix", [1.0 - CALIBRATION_FRACTION], 0.001
    )
    print(
        f"[train_models] calibration cutoff ts_unix = {int(cal_cutoff)}  "
        f"(last {CALIBRATION_FRACTION:.0%} of training reserved for threshold tuning)"
    )
    train = train_full.filter(F.col("ts_unix") <= cal_cutoff)
    calibration_raw = (
        train_full.filter(F.col("ts_unix") > cal_cutoff)
        .persist(StorageLevel.MEMORY_AND_DISK)
    )
    n_cal = calibration_raw.count()
    print(f"[train_models] calibration rows = {n_cal:,}")

    # 2. Downsample negatives + attach class weights on inner-train only, then
    #    repartition to 2× executor cores (15 cores → 30 partitions) so CV
    #    inner stages run in two clean waves of 15 tasks instead of leaving
    #    cores idle on a single tail wave. Cache because CV does
    #    n_combos × numFolds passes over this set — caching amortises the
    #    downsample + orderBy(rand) shuffle across all of them.
    train_balanced = (
        downsample_and_weight(train)
        .repartition(30)
        .persist(StorageLevel.MEMORY_AND_DISK)
    )
    n_balanced = train_balanced.count()  # materialise the cache
    print(
        f"[train_models] balanced train cached: {n_balanced:,} rows / "
        f"{train_balanced.rdd.getNumPartitions()} partitions"
    )

    # 3. Build estimator + hyperparameter grid.
    estimator, grid = builder()
    n_combos = len(grid)
    print(
        f"[train_models] {args.model}: grid size = {n_combos} "
        f"× {CV_FOLDS} folds = {n_combos * CV_FOLDS} fits"
    )

    # 4. CrossValidator — optimizes PR-AUC on the train fold, not ROC-AUC.
    #    PR-AUC is the right metric under heavy imbalance (ml.md §6).
    #    parallelism=4 lets four candidate models fit concurrently against
    #    the 9-core executor pool (~2.25 cores per fit on average). This is
    #    mild over-subscription vs parallelism=3 and improves wall-clock
    #    throughput when individual fits are core-bound for short stretches.
    #    Pushing further (parallelism=6+) starts to compete for the same
    #    cores and hurts more than it helps. YARN allocation is unchanged —
    #    only the driver-side ThreadPoolExecutor that submits parallel jobs.
    evaluator = BinaryClassificationEvaluator(
        labelCol="label",
        rawPredictionCol="rawPrediction",
        metricName="areaUnderPR",
    )
    cv = CrossValidator(
        estimator=estimator,
        estimatorParamMaps=grid,
        evaluator=evaluator,
        numFolds=CV_FOLDS,
        parallelism=4,
        seed=SEED,
        collectSubModels=False,
    )

    # 5. Fit on the balanced train split.
    print(f"[train_models] {args.model}: fitting CrossValidator on train...")
    cv_model = cv.fit(train_balanced)
    best = cv_model.bestModel
    print(
        f"[train_models] {args.model}: best params = "
        f"{ {p.name: best.getOrDefault(p) for p in best.params if best.isSet(p)} }"
    )
    print(f"[train_models] {args.model}: per-combo mean PR-AUC over folds:")
    cv_rows = []
    for combo_idx, (params, metric) in enumerate(zip(grid, cv_model.avgMetrics)):
        compact = {k.name: v for k, v in params.items()}
        param_summary = ", ".join(f"{k}={v}" for k, v in sorted(compact.items()))
        print(f"    PR-AUC={metric:.6f}   {compact}")
        cv_rows.append(
            (args.model, combo_idx, param_summary, float(metric))
        )

    # 5b. Persist CV grid + per-combo PR-AUC so the Stage IV dashboard can
    #     plot hyperparameter-search outcomes (rubric line: "results of
    #     hyper-parameter optimization"). One row per (model, combo).
    cv_path = f"project/output/{model_dir}_cv_results"
    print(f"[train_models] {args.model}: saving CV grid results -> {cv_path}")
    cv_df = spark.createDataFrame(
        cv_rows,
        schema="model string, combo_idx int, params string, avg_pr_auc double",
    )
    (
        cv_df.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(cv_path)
    )

    # Release the cached train set — the rest of main only touches test.
    train_balanced.unpersist()

    # 5c. Pin the production threshold on the calibration tail.
    #     Score calibration with the best CV model, sweep probability
    #     cutoffs, and pick the one that maximises USD recovered subject
    #     to the alerts/day cap. evaluate_models.py reads this CSV and
    #     reports on test at this threshold (not 0.5).
    print(f"[train_models] {args.model}: scoring calibration tail")
    cal_scored = (
        best.transform(calibration_raw)
        .select(
            F.col("label").cast("int").alias("label"),
            vector_to_array("probability")[1].alias("proba_positive"),
            F.col("amount_paid").cast("double").alias("amount_paid"),
            F.col("ts_unix").cast("long").alias("ts_unix"),
        )
        .persist(StorageLevel.MEMORY_AND_DISK)
    )

    ts_min, ts_max = cal_scored.agg(
        F.min("ts_unix"), F.max("ts_unix")
    ).collect()[0]
    cal_days = max(float((ts_max - ts_min) / 86400.0), 1.0)
    budget_alerts = int(cal_days * ALERT_BUDGET_PER_DAY)
    print(
        f"[train_models] {args.model}: calibration span {cal_days:.2f} days, "
        f"alert budget = {budget_alerts:,} ({ALERT_BUDGET_PER_DAY:,}/day)"
    )

    # Single scan over calibration: aggregate (alerts, TP USD) per threshold.
    agg_cols = [
        F.sum(F.when(F.col("label") == 1, F.col("amount_paid")).otherwise(0.0))
            .alias("pos_value"),
    ]
    for thr in CALIBRATION_THRESHOLDS:
        key = int(round(thr * 100))
        agg_cols.append(
            F.sum(F.when(
                (F.col("proba_positive") >= thr) & (F.col("label") == 1),
                F.col("amount_paid"),
            ).otherwise(0.0)).alias(f"tp_val_{key}")
        )
        agg_cols.append(
            F.sum((F.col("proba_positive") >= thr).cast("long"))
                .alias(f"alerts_{key}")
        )
    cal_agg = cal_scored.agg(*agg_cols).collect()[0]
    pos_value = float(cal_agg["pos_value"] or 0.0)

    # Pick max USD-recovered subject to alerts <= budget; tie-break by
    # higher threshold (smaller alert volume).
    best_thr = None
    best_usd = -1.0
    best_alerts = None
    for thr in CALIBRATION_THRESHOLDS:
        key = int(round(thr * 100))
        tp_val = float(cal_agg[f"tp_val_{key}"] or 0.0)
        alerts = int(cal_agg[f"alerts_{key}"] or 0)
        if alerts <= budget_alerts:
            if (tp_val > best_usd) or (tp_val == best_usd and thr > (best_thr or 0)):
                best_thr = thr
                best_usd = tp_val
                best_alerts = alerts
    if best_thr is None:
        # No threshold meets the budget — pin the tightest one (fewest alerts).
        best_thr = CALIBRATION_THRESHOLDS[-1]
        key = int(round(best_thr * 100))
        best_usd = float(cal_agg[f"tp_val_{key}"] or 0.0)
        best_alerts = int(cal_agg[f"alerts_{key}"] or 0)
        print(
            f"[train_models] {args.model}: no threshold satisfies the budget; "
            f"pinning at {best_thr:.2f} (alerts {best_alerts:,})"
        )
    else:
        print(
            f"[train_models] {args.model}: pinned threshold = {best_thr:.2f}  "
            f"USD recovered = ${best_usd/1e9:.2f}B  alerts = {best_alerts:,}"
        )

    pinned_path = f"project/output/{model_dir}_pinned_threshold"
    print(f"[train_models] {args.model}: saving pinned threshold -> {pinned_path}")
    pinned_df = spark.createDataFrame(
        [(
            args.model,
            float(best_thr),
            float(cal_days),
            int(best_alerts or 0),
            float(best_usd),
            float(best_usd / pos_value if pos_value > 0 else 0.0),
            int(ALERT_BUDGET_PER_DAY),
        )],
        schema=("model string, pinned_threshold double, calibration_days double, "
                "calibration_alerts long, calibration_usd_recovered double, "
                "calibration_value_recall double, alert_budget_per_day long"),
    )
    (pinned_df.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(pinned_path))

    cal_scored.unpersist()
    calibration_raw.unpersist()

    # 6. Save best model. The CrossValidatorModel itself is not persisted —
    #    only the best fitted estimator, which is what evaluate_models.py loads.
    model_path = f"project/models/{model_dir}"
    print(f"[train_models] {args.model}: saving best model -> {model_path}")
    best.write().overwrite().save(model_path)

    # 7. Predict on the held-out test split (original imbalance, NO weights).
    #    Carry `amount_paid` and `payment_currency` through so the
    #    probabilities table can support the per-currency value sweep in
    #    evaluate_models.py without re-scoring the test set.
    print(f"[train_models] {args.model}: scoring test split")
    predictions = (
        best.transform(test)
        .select(
            "label",
            "prediction",
            "probability",
            "rawPrediction",
            "amount_paid",
            "payment_currency",
        )
        .persist(StorageLevel.MEMORY_AND_DISK)
    )

    # Test PR-AUC for the report (full evaluation happens in evaluate_models.py).
    test_prauc = evaluator.evaluate(predictions)
    print(f"[train_models] {args.model}: test PR-AUC = {test_prauc:.6f}")

    # 8. Save predictions CSV — keep only (label, prediction) per course spec
    #    "Keep only label and prediction columns. Save it as one partition."
    pred_path = f"project/output/{model_dir}_predictions"
    print(f"[train_models] {args.model}: saving predictions -> {pred_path}")
    (
        predictions.select(
            F.col("label"), F.col("prediction").cast("int").alias("prediction")
        )
        .coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(pred_path)
    )

    # 9. Save probabilities CSV — (label, prediction, proba_positive,
    #    amount_paid, payment_currency). The rubric-mandated _predictions
    #    table above stays schema-pure (label, prediction only); this wider
    #    artefact powers both the count-based threshold sweep and the
    #    per-currency value sweep in evaluate_models.py.
    #
    #    `probability` is a length-2 Vector for binary classification —
    #    [P(class 0), P(class 1)] — so index 1 is the positive class
    #    probability. vector_to_array is a Catalyst-native expression
    #    (Spark 3.0+), faster than a Python UDF.
    prob_path = f"project/output/{model_dir}_probabilities"
    print(f"[train_models] {args.model}: saving probabilities -> {prob_path}")
    (
        predictions.select(
            F.col("label"),
            F.col("prediction").cast("int").alias("prediction"),
            vector_to_array("probability")[1].alias("proba_positive"),
            F.col("amount_paid").cast("double").alias("amount_paid"),
            F.col("payment_currency").alias("payment_currency"),
        )
        .coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(prob_path)
    )

    predictions.unpersist()

    # 10. Register Hive external tables over the three CSV outputs so the
    #     Stage IV Apache Superset dashboard can read them directly from
    #     the Hive metastore (rubric: "Create external Hive tables for
    #     results of stage III"). Each TBLPROPERTIES skips the CSV header
    #     row. Paths are absolute to avoid the Spark-vs-Hive relative-path
    #     resolution mismatch documented in build_features.py.
    pred_table = f"{HIVE_DB}.{model_dir}_predictions"
    prob_table = f"{HIVE_DB}.{model_dir}_probabilities"
    cv_table = f"{HIVE_DB}.{model_dir}_cv_results"
    pred_abs = f"/user/team1/{pred_path}"
    prob_abs = f"/user/team1/{prob_path}"
    cv_abs = f"/user/team1/{cv_path}"

    print(f"[train_models] {args.model}: registering Hive table {pred_table}")
    spark.sql(f"DROP TABLE IF EXISTS {pred_table}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {pred_table} (
                label      INT,
                prediction INT
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{pred_abs}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    print(f"[train_models] {args.model}: registering Hive table {prob_table}")
    spark.sql(f"DROP TABLE IF EXISTS {prob_table}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {prob_table} (
                label            INT,
                prediction       INT,
                proba_positive   DOUBLE,
                amount_paid      DOUBLE,
                payment_currency STRING
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{prob_abs}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    print(f"[train_models] {args.model}: registering Hive table {cv_table}")
    spark.sql(f"DROP TABLE IF EXISTS {cv_table}")
    spark.sql(
        f"""CREATE EXTERNAL TABLE {cv_table} (
                model      STRING,
                combo_idx  INT,
                params     STRING,
                avg_pr_auc DOUBLE
            )
            ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
            STORED AS TEXTFILE
            LOCATION '{cv_abs}'
            TBLPROPERTIES ('skip.header.line.count'='1')"""
    )

    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
