"""Stage IV — extract model + pipeline metadata for the Superset dashboard.

Loads three Stage III artefacts already on HDFS:
    project/data/feature_pipeline   (saved PipelineModel)
    project/models/model1           (saved LogisticRegressionModel)
    project/models/model2           (saved GBTClassificationModel)

and writes three small CSVs that the Stage IV dashboard charts directly:

    project/output/dashboard/feature_extraction/
        stage_type, input_col, output_col, n_categories, top_label
        One row per stage of the saved feature pipeline — exposes the
        StringIndexer vocabularies + OneHotEncoder / VectorAssembler wiring.

    project/output/dashboard/hyperparam/
        model, param_name, param_value
        The BEST hyperparameters picked by CrossValidator for each model.
        Pairs with project/output/cv_results_modelN (written by
        train_models.py) which holds the full grid sweep.

    project/output/dashboard/feature_importance/
        feature_index, importance
        GBT featureImportances. The dashboard joins this against the
        assembler input-column list to show which features carry weight.

Each output is coalesced to one part file so the downstream Hive external
table sees a single CSV (plus header). External-table DDL lives in
sql/stage4_views.hql.
"""
import sys

from pyspark.ml import PipelineModel
from pyspark.ml.classification import GBTClassificationModel, LogisticRegressionModel

from spark_session import build_session


HDFS_PIPELINE = "project/data/feature_pipeline"
HDFS_MODEL1 = "project/models/model1"
HDFS_MODEL2 = "project/models/model2"

HDFS_OUT_FEATURE_EXTRACT = "project/output/dashboard/feature_extraction"
HDFS_OUT_HYPERPARAM = "project/output/dashboard/hyperparam"
HDFS_OUT_FEATURE_IMPORTANCE = "project/output/dashboard/feature_importance"


def _safe_param_get(stage, name):
    """Return the value of a named Param on a stage, or '' if unset / absent.

    Spark ML params raise on missing keys; this wrapper falls back to ''
    so we can treat every stage the same way regardless of which params
    it declares.
    """
    if not stage.hasParam(name):
        return ""
    p = stage.getParam(name)
    if not stage.isDefined(p):
        return ""
    val = stage.getOrDefault(p)
    if isinstance(val, (list, tuple)):
        return ",".join(str(x) for x in val)
    return str(val)


def extract_feature_pipeline_summary(spark, pipeline):
    """One row per stage of the saved feature pipeline."""
    rows = []
    for stage in pipeline.stages:
        stage_type = type(stage).__name__
        # inputCol (single-col stages: StringIndexer, OneHotEncoder, SinCosEncoder)
        # or inputCols (multi-col stages: VectorAssembler). Probe both.
        input_col = _safe_param_get(stage, "inputCol") or _safe_param_get(stage, "inputCols")
        output_col = _safe_param_get(stage, "outputCol") or _safe_param_get(stage, "outputCols")

        n_categories = -1
        top_label = ""
        # StringIndexerModel exposes .labels — use it as the duck-type probe
        # so the code stays correct if we reorder pipeline stages.
        if hasattr(stage, "labels"):
            labels = list(stage.labels)
            n_categories = len(labels)
            top_label = labels[0] if labels else ""

        rows.append((stage_type, input_col, output_col, n_categories, top_label))

    return spark.createDataFrame(
        rows,
        schema=("stage_type string, input_col string, output_col string, "
                "n_categories int, top_label string"),
    )


def extract_best_params(spark, model_name, model):
    """One row per (model, param_name) for the BEST fit's explicitly set params.

    Skips Vector / list-typed params (intercept vectors etc.) that don't fit
    a flat CSV. The grader gets the scalar hyperparameters that motivated
    the model selection — regParam, elasticNetParam, maxDepth, subsamplingRate
    — plus the fixed training controls (maxIter, family, seed, ...).
    """
    rows = []
    for p in model.params:
        if not model.isSet(p):
            continue
        val = model.getOrDefault(p)
        if isinstance(val, (int, float, str, bool)):
            rows.append((model_name, p.name, str(val)))
    return spark.createDataFrame(
        rows,
        schema="model string, param_name string, param_value string",
    )


def extract_feature_importance(spark, model):
    """Dense (index, importance) rows from GBTClassificationModel.featureImportances."""
    fi = model.featureImportances.toArray()
    rows = [(int(i), float(v)) for i, v in enumerate(fi)]
    return spark.createDataFrame(
        rows,
        schema="feature_index int, importance double",
    )


def write_single_csv(df, path):
    """Coalesce-1 CSV write with header — matches the format Hive externals expect."""
    (df.coalesce(1)
       .write.mode("overwrite")
       .option("header", "true")
       .csv(path))


def main():
    spark = build_session("stage4_prepare")

    print(f"[stage4_prepare] loading pipeline from {HDFS_PIPELINE}")
    pipeline = PipelineModel.load(HDFS_PIPELINE)
    fe_df = extract_feature_pipeline_summary(spark, pipeline)
    print(f"[stage4_prepare] feature pipeline: {fe_df.count()} stages")
    fe_df.show(truncate=False)
    write_single_csv(fe_df, HDFS_OUT_FEATURE_EXTRACT)

    print(f"[stage4_prepare] loading model1 from {HDFS_MODEL1}")
    m1 = LogisticRegressionModel.load(HDFS_MODEL1)
    p1 = extract_best_params(spark, "model1_LogisticRegression", m1)

    print(f"[stage4_prepare] loading model2 from {HDFS_MODEL2}")
    m2 = GBTClassificationModel.load(HDFS_MODEL2)
    p2 = extract_best_params(spark, "model2_GBTClassifier", m2)

    hp_df = p1.union(p2)
    print(f"[stage4_prepare] hyperparams: {hp_df.count()} rows")
    hp_df.show(truncate=False)
    write_single_csv(hp_df, HDFS_OUT_HYPERPARAM)

    fi_df = extract_feature_importance(spark, m2)
    print(f"[stage4_prepare] feature importance: {fi_df.count()} features")
    (fi_df.orderBy(fi_df.importance.desc())
          .show(10, truncate=False))
    write_single_csv(fi_df, HDFS_OUT_FEATURE_IMPORTANCE)

    print("[stage4_prepare] done. HDFS outputs:")
    for label, path in [
        ("feature extraction", HDFS_OUT_FEATURE_EXTRACT),
        ("hyperparam best   ", HDFS_OUT_HYPERPARAM),
        ("feature importance", HDFS_OUT_FEATURE_IMPORTANCE),
    ]:
        print(f"    {label}  ->  {path}")

    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
