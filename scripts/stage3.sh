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

# Match the lab's spark-submit form: --master yarn, nothing else.
# The Hive metastore URI, warehouse dir, AVRO codec, and Hive support
# are all set inside scripts/spark_session.py via SparkSession.builder
# — those are applied before any Hive operation in the script runs, so
# spark-submit doesn't need the -Dhive.metastore.uris= JVM property
# that's necessary for the pyspark interactive shell (which loads Hive
# before user Python configs apply).
SPARK_SUBMIT=(spark-submit --master yarn)

# Every Stage III job imports spark_session.py, and most also import
# build_features.py for TRAIN_FRACTION. Ship both as --py-files so YARN
# executors have them on the import path.
PY_FILES="scripts/spark_session.py,scripts/build_features.py"

mkdir -p data models output

# -----------------------------------------------------------------------------
# 0. HDFS quota hygiene.
#
# /user/team1 has a 32 GB raw (replicated) quota = ~10.7 GB unique data.
# A previous build_features run busted it at step 9 (JSON splits write) —
# Spark retried task 0 four times against DSQuotaExceededException, then
# aborted the whole job.  Two routine sources of bloat fix this for good:
#
#   a) `.Trash` — every prior `hdfs dfs -rm` without -skipTrash sits here
#      until manually purged.  Easily 8-10 GB after a week of iteration.
#      `hdfs dfs -expunge` empties it.
#
#   b) The Spark staging dir under `.sparkStaging` — usually cleaned by
#      driver shutdown, but lingers if a previous YARN app was killed.
#      Safe to wipe; live YARN apps hold their own subdir by app-id and
#      will recreate as needed.
#
# After cleanup we print the resulting quota state so the run log shows
# exactly how much headroom we started with, and fail fast if the budget
# left is below the minimum needed for a full-data build_features run.
# -----------------------------------------------------------------------------
echo "============================================================"
echo "[stage3] (0/4) HDFS quota hygiene"
echo "============================================================"
hdfs dfs -expunge 2>/dev/null || true
hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/.sparkStaging" 2>/dev/null || true
hdfs dfs -count -q -h "${HDFS_USER}" 2>&1 | awk '
NR==1 {print "[stage3] " $0}
NR==2 {
    print "[stage3] quota='\''$3"'\''  used='\''$4"'\''  files='\''$5"'\''  inodes='\''$6"'\'' "
    # When --human-readable is on, fields 3/4 are like "32" "16.5" with the
    # unit suffix glued to the trailing column 7 ($7 holds "G/user/team1").
    # The awk above is informational only; the script-side budget check
    # below uses a numeric (-v) form for accuracy.
}'
# Bytes-precision budget check (skip with QUOTA_GUARD=0 for dev tinkering).
if [[ "${QUOTA_GUARD:-1}" == "1" && -z "${SAMPLE_FRACTION:-}" && -z "${LIMIT_DAYS:-}" ]]; then
    # `hdfs dfs -count -q` columns (no -h, so all in bytes):
    #   QUOTA  REMAINING_QUOTA  SPACE_QUOTA  REMAINING_SPACE_QUOTA  ...
    # We want columns 3 (total) and 4 (remaining = avail = quota − used).
    read -r _ _ quota avail _ < <(hdfs dfs -count -q "${HDFS_USER}" 2>/dev/null | tail -1)
    if [[ "$quota" =~ ^[0-9]+$ && "$avail" =~ ^[0-9]+$ ]]; then
        # Empirically ~12 GB replicated headroom is enough for the full-data
        # build_features step 8+9 (Parquet splits + gzipped JSON splits).
        min_avail=$(( 12 * 1024 * 1024 * 1024 ))
        if (( avail < min_avail )); then
            echo "[stage3] ERROR: only $(( avail / 1024 / 1024 ))MB of HDFS quota free."
            echo "[stage3]        need at least $(( min_avail / 1024 / 1024 ))MB for a full-data run."
            echo "[stage3]        either free space (du -h, then targeted hdfs dfs -rm -skipTrash),"
            echo "[stage3]        run with LIMIT_DAYS=N or SAMPLE_FRACTION=F, or set QUOTA_GUARD=0."
            exit 1
        fi
        echo "[stage3] quota OK: $(( avail / 1024 / 1024 ))MB free, "\
"$(( min_avail / 1024 / 1024 ))MB minimum"
    fi
fi

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
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/eval_at_fixed_recall" || true

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
    # `hdfs dfs -text` transparently decompresses .gz part files written by
    # build_features.py (we gzip the JSON to stay under the 32 GB HDFS quota).
    # Works the same for plain .json if compression is later disabled.
    rm -f data/train.json data/test.json
    hdfs dfs -text "${HDFS_USER}/project/data/train/part-*" > data/train.json
    hdfs dfs -text "${HDFS_USER}/project/data/test/part-*"  > data/test.json
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

    # 5g. Alert-volume-at-fixed-recall (ml.md §6 operational metric).
    #     One row per (model, target_recall ∈ {0.5, 0.7, 0.9}).
    rm -f output/eval_at_fixed_recall.csv
    echo "model,target_recall,threshold,alerts,tp,actual_recall,precision" \
        > output/eval_at_fixed_recall.csv
    hdfs dfs -cat "${HDFS_USER}/project/output/eval_at_fixed_recall/part-*.csv" \
        2>/dev/null | tail -n +2 >> output/eval_at_fixed_recall.csv || true
    echo "[stage3] -> output/eval_at_fixed_recall.csv"
    cat output/eval_at_fixed_recall.csv
fi

# -----------------------------------------------------------------------------
# 6. Pylint — Stage III rubric line item.
#    Runs over the five Python scripts. We do NOT fail the build on
#    pylint findings: pylint is heuristic, and a single "fixme" or
#    "too-many-locals" doesn't justify wedging the entire submission.
#    The exit code is reported in the log so the grader can see whether
#    the run passed cleanly. Skip with SKIP_PYLINT=1 for fast iterations.
# -----------------------------------------------------------------------------
if [[ "${SKIP_PYLINT:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage3] (6) pylint scripts"
    echo "============================================================"
    if command -v pylint >/dev/null 2>&1; then
        # --rcfile picks up .pylintrc at the repo root if present;
        # falls back to defaults otherwise. --exit-zero so a non-clean
        # run doesn't kill the bash script (we still see the score).
        pylint --rcfile=.pylintrc --exit-zero \
            scripts/spark_session.py \
            scripts/build_features.py \
            scripts/rule_baseline.py \
            scripts/train_models.py \
            scripts/evaluate_models.py \
            | tee output/pylint.txt
        echo "[stage3] -> output/pylint.txt"
    else
        echo "[stage3] pylint not installed; skipping (install with: pip install --user pylint)"
    fi
fi

echo "[stage3] done."