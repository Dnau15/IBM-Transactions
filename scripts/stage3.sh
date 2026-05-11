#!/usr/bin/env bash
# Stage III — Predictive Data Analytics.
# Runs four spark-submit jobs in order:
#   1) build_features.py   — Tier 1 vertex stats + temporal 80/20 split
#   2) rule_baseline.py    — R1/R2/R5 SQL rules (single operating point)
#   3) train_models.py --model lr   — LogisticRegression  (model1, classical)
#      train_models.py --model gbt  — GBTClassifier       (model2, non-classical)
#   4) evaluate_models.py  — combined evaluation.csv
#
# Then pulls all HDFS outputs back into the local repo so the grader can
# inspect data/{train,test}.json, models/, output/ without HDFS access.
#
# Phases can be skipped via env var for iterative re-runs:
#   SKIP_FEATURES=1   skip build_features.py
#   SKIP_RULES=1      skip rule_baseline.py
#   SKIP_LR=1         skip LogisticRegression training
#   SKIP_GBT=1        skip GBTClassifier training
#   SKIP_EVAL=1       skip evaluate_models.py
#   SKIP_PULL=1       skip the HDFS-to-local copy at the end
#
# Dev-mode dataset-size knobs (consumed by build_features.py; downstream
# scripts read the resulting features table and automatically inherit
# the subset). Both are independent and combinable:
#   SAMPLE_FRACTION=0.01  random 1% row sample (fastest, lossy windows)
#   LIMIT_DAYS=2          keep only first N days (windows stay accurate)
#
# Examples:
#   bash scripts/stage3.sh                              # full prod run
#   SAMPLE_FRACTION=0.01 bash scripts/stage3.sh         # 1% smoke test
#   LIMIT_DAYS=2 bash scripts/stage3.sh                 # 2-day subset
#   LIMIT_DAYS=4 SAMPLE_FRACTION=0.5 bash scripts/stage3.sh  # combined
set -euo pipefail

# Export dev-mode knobs so they reach the spark-submit driver Python.
# Each variable is exported only if set in the caller's environment.
[[ -n "${SAMPLE_FRACTION:-}" ]] && export SAMPLE_FRACTION
[[ -n "${LIMIT_DAYS:-}"      ]] && export LIMIT_DAYS
if [[ -n "${SAMPLE_FRACTION:-}" || -n "${LIMIT_DAYS:-}" ]]; then
    echo "[stage3] DEV MODE active: SAMPLE_FRACTION=${SAMPLE_FRACTION:-<unset>}  LIMIT_DAYS=${LIMIT_DAYS:-<unset>}"
fi

TEAM="team1"
HDFS_USER="/user/${TEAM}"
METASTORE_URI="thrift://hadoop-02.uni.innopolis.ru:9883"

# Cluster's system Python (3.6) ships pyspark 3.2.4 in /usr/local/lib/...;
# our .venv311 masks that and breaks spark-submit. Same incantation as
# stage2.sh — see comment there for the full story.
unset PYSPARK_PYTHON PYSPARK_DRIVER_PYTHON VIRTUAL_ENV

# Force UTF-8 stdout for the driver Python. The cluster's Python 3.6
# defaults to an ASCII stdout, so any non-ASCII character in a log
# message (we use em-dashes liberally) raises UnicodeEncodeError mid-log
# — non-fatal, but adds a noisy traceback after every affected line.
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Hive metastore URI is bound THREE ways for robustness — without this an
# interactively-launched pyspark sees team1_projectdb.* fine but a
# spark-submit driver silently falls back to a local Derby metastore,
# leading to SHOW TABLES "working" but returning empty / wrong content.
#
#   1) spark.hadoop.hive.metastore.uris — Spark propagates this into the
#      Hadoop/Hive client conf. Modern, recommended path.
#   2) spark.{driver,executor}.extraJavaOptions=-Dhive.metastore.uris=…
#      JVM-level fallback. Some Hive client init paths read the URI from
#      system properties before SparkConf is applied; this catches anything
#      (1) misses, and is the same flag we use when launching pyspark
#      interactively.
#   3) spark_session.py also sets it via .config("hive.metastore.uris", …)
#      as a third belt-and-braces layer.
#
# spark.sql.catalogImplementation=hive guarantees the Hive catalog is
# chosen even if enableHiveSupport() doesn't get called (e.g. when
# something pre-creates a SparkSession before build_session()).
SPARK_SUBMIT=(
    spark-submit
    --master yarn
    --deploy-mode client
    --conf "spark.sql.catalogImplementation=hive"
    --conf "spark.hadoop.hive.metastore.uris=${METASTORE_URI}"
    --conf "spark.driver.extraJavaOptions=-Dhive.metastore.uris=${METASTORE_URI}"
    --conf "spark.executor.extraJavaOptions=-Dhive.metastore.uris=${METASTORE_URI}"
)

# Every Stage III job imports spark_session.py, and most also import
# build_features.py for TRAIN_FRACTION. Ship both as --py-files so YARN
# executors have them on the import path.
PY_FILES="scripts/spark_session.py,scripts/build_features.py"

mkdir -p data models output

# -----------------------------------------------------------------------------
# 1. Feature engineering + temporal split
# -----------------------------------------------------------------------------
if [[ "${SKIP_FEATURES:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage3] (1/4) build_features.py"
    echo "============================================================"
    # Clean HDFS targets — build_features.py overwrites anyway, but a
    # leftover features Hive table from a previous schema can wedge
    # CREATE EXTERNAL TABLE.
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/data" || true

    "${SPARK_SUBMIT[@]}" --py-files "$PY_FILES" scripts/build_features.py
fi

# -----------------------------------------------------------------------------
# 2. Rule baseline
# -----------------------------------------------------------------------------
if [[ "${SKIP_RULES:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage3] (2/4) rule_baseline.py"
    echo "============================================================"
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/rule_baseline" || true

    "${SPARK_SUBMIT[@]}" --py-files "$PY_FILES" scripts/rule_baseline.py
fi

# -----------------------------------------------------------------------------
# 3a. Train model1 — LogisticRegression
# -----------------------------------------------------------------------------
if [[ "${SKIP_LR:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage3] (3a/4) train_models.py --model lr   [model1]"
    echo "============================================================"
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/models/model1" || true
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/model1_predictions" || true

    "${SPARK_SUBMIT[@]}" --py-files "$PY_FILES" scripts/train_models.py --model lr
fi

# -----------------------------------------------------------------------------
# 3b. Train model2 — GBTClassifier
# -----------------------------------------------------------------------------
if [[ "${SKIP_GBT:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage3] (3b/4) train_models.py --model gbt  [model2]"
    echo "============================================================"
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/models/model2" || true
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/model2_predictions" || true

    "${SPARK_SUBMIT[@]}" --py-files "$PY_FILES" scripts/train_models.py --model gbt
fi

# -----------------------------------------------------------------------------
# 4. Evaluation comparison
# -----------------------------------------------------------------------------
if [[ "${SKIP_EVAL:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage3] (4/4) evaluate_models.py"
    echo "============================================================"
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/evaluation" || true
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/eval_pattern_recall" || true
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/eval_weekend_weekday" || true

    "${SPARK_SUBMIT[@]}" --py-files "$PY_FILES" scripts/evaluate_models.py
fi

# -----------------------------------------------------------------------------
# 5. Pull HDFS outputs back into the local repo for the grader.
#    Per Stage III spec:  data/train.json, data/test.json,
#    models/modelN, output/modelN_predictions.csv, output/evaluation.csv
# -----------------------------------------------------------------------------
if [[ "${SKIP_PULL:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage3] (5/4) pulling HDFS outputs into local repo"
    echo "============================================================"

    # 5a. Train / test JSON — concat HDFS part files into a single
    #     local file (we coalesce(1) in build_features.py, so there's only
    #     one part-*.json each; -cat ... still works for safety).
    rm -f data/train.json data/test.json
    hdfs dfs -cat "${HDFS_USER}/project/data/train/part-*.json" > data/train.json
    hdfs dfs -cat "${HDFS_USER}/project/data/test/part-*.json"  > data/test.json
    echo "[stage3] -> data/train.json  ($(wc -l < data/train.json) lines)"
    echo "[stage3] -> data/test.json   ($(wc -l < data/test.json) lines)"

    # 5b. Models — full Spark ML model directories (metadata + parquet
    #     coefficients). -get clobbers existing local dirs.
    rm -rf models/model1 models/model2
    hdfs dfs -get "${HDFS_USER}/project/models/model1" models/model1
    hdfs dfs -get "${HDFS_USER}/project/models/model2" models/model2
    echo "[stage3] -> models/model1, models/model2"

    # 5c. Predictions CSV — strip HDFS partition dir into a single local CSV
    #     with a real header line.
    for m in model1 model2; do
        local_csv="output/${m}_predictions.csv"
        rm -f "$local_csv"
        echo "label,prediction" > "$local_csv"
        hdfs dfs -cat "${HDFS_USER}/project/output/${m}_predictions/part-*.csv" \
            | tail -n +2 >> "$local_csv" || true
        echo "[stage3] -> $local_csv ($(($(wc -l < "$local_csv") - 1)) rows)"
    done

    # 5d. Evaluation CSV — same single-CSV treatment.
    rm -f output/evaluation.csv
    echo "model,precision,recall,f1,pr_auc,alert_volume" > output/evaluation.csv
    hdfs dfs -cat "${HDFS_USER}/project/output/evaluation/part-*.csv" \
        | tail -n +2 >> output/evaluation.csv
    echo "[stage3] -> output/evaluation.csv:"
    cat output/evaluation.csv

    # 5e. Pattern-recall breakdown (per-canonical-type, per-model).
    rm -f output/eval_pattern_recall.csv
    echo "model,canon_type,n_groups,n_caught,recall" > output/eval_pattern_recall.csv
    hdfs dfs -cat "${HDFS_USER}/project/output/eval_pattern_recall/part-*.csv" \
        2>/dev/null | tail -n +2 >> output/eval_pattern_recall.csv || true
    echo "[stage3] -> output/eval_pattern_recall.csv"
    cat output/eval_pattern_recall.csv

    # 5f. Weekend/weekday recall breakdown.
    rm -f output/eval_weekend_weekday.csv
    echo "model,segment,n_positives,n_caught,recall" > output/eval_weekend_weekday.csv
    hdfs dfs -cat "${HDFS_USER}/project/output/eval_weekend_weekday/part-*.csv" \
        2>/dev/null | tail -n +2 >> output/eval_weekend_weekday.csv || true
    echo "[stage3] -> output/eval_weekend_weekday.csv"
    cat output/eval_weekend_weekday.csv
fi

echo "[stage3] done."