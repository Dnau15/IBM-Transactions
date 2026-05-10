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
    source .venv311/bin/activate
    pip install -q -U pip
    pip install -q -r requirements.txt
    spark-submit --master yarn --deploy-mode client scripts/load_accounts.py
fi

[[ "${SKIP_HIVE:-0}"     == "1" ]] || ./scripts/build_hive_db.sh
[[ "${SKIP_EDA:-0}"      == "1" ]] || ./scripts/run_eda.sh

if [[ "${RUN_PLOTS:-1}" == "1" && "${SKIP_PLOTS:-0}" != "1" ]]; then
    if .venv311/bin/python -c "import matplotlib" 2>/dev/null; then
        .venv311/bin/python scripts/eda_plot.py
    else
        echo "[stage2] matplotlib not available; skipping eda_plot.py"
        echo "[stage2] (run pip install -r requirements.txt to enable)"
    fi
fi

echo "[stage2] done."
