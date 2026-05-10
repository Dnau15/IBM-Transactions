#!/usr/bin/env bash
# Stage I — data download. Uses Kaggle CLI (durable) instead of expiring
# GCS signed URLs. Idempotent: existing files in data/ are not re-downloaded.
#
# Credentials: place a Kaggle API token at secrets/kaggle.json (gitignored)
# OR have ~/.kaggle/kaggle.json on the host. Get a token from
# https://www.kaggle.com/settings → "Create New API Token".
set -euo pipefail

DATASET="ealtman2019/ibm-transactions-for-anti-money-laundering-aml"

source .venv311/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt

# Prefer team-local credentials so multiple users on the cluster don't
# share a single ~/.kaggle dir.
if [[ -f secrets/kaggle.json ]]; then
    chmod 600 secrets/kaggle.json
    export KAGGLE_CONFIG_DIR="$(pwd)/secrets"
fi

mkdir -p data/

download_one() {
    local src="$1" dst="$2"
    if [[ -s "data/${dst}" ]]; then
        echo "[data_collection] data/${dst} already present — skipping ${src}"
        return 0
    fi
    echo "[data_collection] kaggle pull ${src} -> data/${dst}"
    kaggle datasets download -d "$DATASET" -f "$src" -p data/ --force

    # Kaggle wraps larger single-file downloads in .zip; smaller ones land raw.
    if [[ -f "data/${src}.zip" ]]; then
        unzip -o "data/${src}.zip" -d data/
        rm -f "data/${src}.zip"
    fi

    if [[ ! -f "data/${src}" ]]; then
        echo "ERROR: expected data/${src} after kaggle download" >&2
        exit 1
    fi
    mv -f "data/${src}" "data/${dst}"
}

download_one HI-Medium_Trans.csv     transactions.csv
download_one HI-Medium_accounts.csv  accounts.csv
download_one HI-Medium_Patterns.txt  patterns.txt

echo "[data_collection] data/ contents:"
ls -lh data/
