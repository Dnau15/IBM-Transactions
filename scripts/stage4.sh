#!/usr/bin/env bash
# Stage IV — Presentation & Delivery.
#
# Materialises everything the Apache Superset dashboard charts:
#
#   1) stage4_prepare.py  — Spark job that loads the saved feature pipeline
#                           + both models and writes three small CSVs to
#                           HDFS (feature extraction, hyperparams, GBT
#                           feature importance).
#   2) sql/stage4_views.hql — beeline DDL that registers external Hive
#                           tables over every Stage III + Stage IV output
#                           CSV so Superset can query them.
#   3) pylint              — rubric line item.
#
# The dashboard itself is built MANUALLY in Apache Superset (per Stage IV
# rubric: "Write scripts to automate the tasks above except the tasks in
# Apache Superset"). Reference SQL for the Postgres data-description tab
# lives in sql/stage4_data_description.sql.
#
# Phases (chain freely on re-runs):
#   SKIP_PREPARE=1  skip the spark-submit prep job
#   SKIP_VIEWS=1    skip the beeline DDL
#   SKIP_PYLINT=1   skip pylint
set -euo pipefail

# Same unset incantation as stage2.sh / stage3.sh — Python 3.11 venv masks
# the cluster's pyspark 3.2.4 and makes spark-submit fall back to an older
# /usr/lib/spark with incompatible cloudpickle. See CLAUDE.md.
unset PYSPARK_PYTHON PYSPARK_DRIVER_PYTHON VIRTUAL_ENV
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

TEAM="team1"
HDFS_USER="/user/${TEAM}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p output

# ----------------------------------------------------------------------------
# 1. Spark prep job — model + pipeline metadata to HDFS CSV.
# ----------------------------------------------------------------------------
if [[ "${SKIP_PREPARE:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage4] (1/3) stage4_prepare.py — model + pipeline metadata"
    echo "============================================================"

    # Clear previous dashboard outputs so stage4_prepare.py writes into a
    # clean tree. Each .mode("overwrite") on the inner paths already clears
    # that subdir, but pre-clearing the parent makes the run self-contained
    # if the schema of the prep CSVs ever changes.
    hdfs dfs -rm -r -f -skipTrash "${HDFS_USER}/project/output/dashboard" || true

    spark-submit --master yarn \
        --py-files scripts/spark_session.py,scripts/build_features.py \
        scripts/stage4_prepare.py
fi

# ----------------------------------------------------------------------------
# 2. Register Hive external tables for every Superset-visible CSV.
# ----------------------------------------------------------------------------
if [[ "${SKIP_VIEWS:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage4] (2/3) beeline -f sql/stage4_views.hql"
    echo "============================================================"

    # Same -w tmpfile pattern as build_hive_db.sh / run_eda.sh — avoids
    # leaking the password through /proc/$pid/cmdline that `beeline -p ...`
    # would expose to anyone running `ps`.
    PWDFILE=$(mktemp)
    chmod 600 "$PWDFILE"
    head -n1 secrets/.hive.pass | tr -d '\n' > "$PWDFILE"
    trap 'rm -f "$PWDFILE"' EXIT

    beeline -u "jdbc:hive2://hadoop-03.uni.innopolis.ru:10001" \
        -n "$TEAM" -w "$PWDFILE" \
        --hiveconf hive.execution.engine=tez \
        -f sql/stage4_views.hql 2>&1 | tee output/stage4_views.log

    echo "[stage4] -> output/stage4_views.log"
fi

# ----------------------------------------------------------------------------
# 3. Pylint on stage4 scripts — rubric line item.
# ----------------------------------------------------------------------------
if [[ "${SKIP_PYLINT:-0}" != "1" ]]; then
    echo "============================================================"
    echo "[stage4] (3/3) pylint scripts/stage4_prepare.py"
    echo "============================================================"
    if command -v pylint >/dev/null 2>&1; then
        pylint --rcfile="${REPO_ROOT}/.pylintrc" --exit-zero \
            "${REPO_ROOT}/scripts/stage4_prepare.py" \
            | tee output/pylint_stage4.txt
        echo "[stage4] -> output/pylint_stage4.txt"
    else
        echo "[stage4] pylint not installed; skipping (pip install --user pylint)"
    fi
fi

# ----------------------------------------------------------------------------
# 4. Tell the operator what they still have to do manually in Superset.
# ----------------------------------------------------------------------------
cat <<'EOM'

============================================================
[stage4] automated steps done. Remaining work in Apache Superset (manual,
        per rubric "automate everything except Superset tasks"):

  1. In Superset, ensure the team1 Hive + team1 Postgres datasources are
     present (Settings → Database Connections).

  2. Create datasets from these Hive tables — they were created by step (2):
       team1_projectdb.evaluation                  (headline comparison)
       team1_projectdb.rule_baseline_dataset       (rule baseline detail)
       team1_projectdb.feature_extraction_summary  (pipeline stages)
       team1_projectdb.hyperparam_summary          (best hyperparams)
       team1_projectdb.cv_results_model1           (LR grid sweep)
       team1_projectdb.cv_results_model2           (GBT grid sweep)
       team1_projectdb.feature_importance          (GBT importances)
       team1_projectdb.model1_predictions          (LR confusion)
       team1_projectdb.model2_predictions          (GBT confusion)
       team1_projectdb.q1_results ... q20_results  (Stage II EDA)
       team1_projectdb.b1_results ... b16_results  (business queries)

  3. Run the queries in sql/stage4_data_description.sql against the Postgres
     datasource for the Data Description tab (row counts, dtypes, samples).

  4. Build the dashboard layout per docs/report.md §6.1:
       Tab 1 — Data Description (Postgres queries above)
       Tab 2 — Data Insights (qN_results / bN_results charts + a markdown
               conclusion under each)
       Tab 3 — ML Modelling (feature_extraction_summary,
               hyperparam_summary, cv_results_model{1,2},
               feature_importance, evaluation, modelN_predictions)

  5. Publish the dashboard and export chart screenshots to output/ as
     needed for the final report.
============================================================

EOM

echo "[stage4] done."
