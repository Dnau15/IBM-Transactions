#!/usr/bin/env bash
# Stage II driver: Hive warehouse build + EDA queries + matplotlib backups.
# Mirrors stage1.sh structure. Each phase can be skipped via env var so
# iterative re-runs only redo what changed.
#
# Phases:
#   SKIP_AVSC=1     : skip uploading *.avsc to HDFS
#   SKIP_ACCOUNTS=1 : skip CSV->Parquet load of accounts.csv
#   SKIP_HIVE=1     : skip db.hql (Hive DB + tables creation)
#   SKIP_EDA=1      : skip running q1..q9
#   SKIP_PLOTS=1    : skip matplotlib backups (default skip if matplotlib
#                     missing; explicit RUN_PLOTS=1 to force)
set -euo pipefail

chmod +x scripts/upload_avsc.sh
chmod +x scripts/build_hive_db.sh
chmod +x scripts/run_eda.sh

[[ "${SKIP_AVSC:-0}"     == "1" ]] || ./scripts/upload_avsc.sh

if [[ "${SKIP_ACCOUNTS:-0}" != "1" ]]; then
    # Use the cluster's system Python (3.6) which ships pyspark 3.2.4 in
    # /usr/local/lib/python3.6/site-packages/. Activating .venv311 (3.11)
    # masks that pyspark and makes spark-submit fall back to an older
    # /usr/lib/spark install whose cloudpickle is incompatible with 3.11.
    unset PYSPARK_PYTHON PYSPARK_DRIVER_PYTHON VIRTUAL_ENV
    spark-submit --master yarn --deploy-mode client scripts/load_accounts.py
fi

[[ "${SKIP_HIVE:-0}"     == "1" ]] || ./scripts/build_hive_db.sh
[[ "${SKIP_EDA:-0}"      == "1" ]] || ./scripts/run_eda.sh

if [[ "${RUN_PLOTS:-1}" == "1" && "${SKIP_PLOTS:-0}" != "1" ]]; then
    # Try plots; if matplotlib/pandas can't be imported, attempt a pip
    # install (pinned versions ship manylinux2014 wheels for cluster glibc).
    # Fail-soft: if install can't satisfy on this host, the Superset .jpg
    # exports remain the primary chart deliverable per spec.
    if .venv311/bin/python -c "import matplotlib, pandas" 2>/dev/null; then
        .venv311/bin/python scripts/eda_plot.py
    else
        echo "[stage2] plot deps missing — attempting install ..."
        if .venv311/bin/pip install -q -r requirements.txt; then
            .venv311/bin/python scripts/eda_plot.py
        else
            echo "[stage2] WARNING: plot deps could not be installed; skipping mpl backups"
            echo "[stage2] (Superset chart exports at output/qN.jpg remain the primary deliverable)"
        fi
    fi
fi

echo "[stage2] done."
