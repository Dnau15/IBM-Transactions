#!/usr/bin/env bash
set -euo pipefail

chmod +x scripts/data_collection.sh
chmod +x scripts/convert.sh
chmod +x scripts/data_storage.sh
chmod +x scripts/data_ingestion.sh
chmod +x scripts/benchmark_formats.sh

./scripts/data_collection.sh
./scripts/convert.sh
./scripts/data_storage.sh
./scripts/data_ingestion.sh

# Benchmark sweep is opt-in: ~30 min of sequential Sqoop imports. Run
# from main.sh with --with-bench, or directly with WITH_BENCH=1.
if [[ "${WITH_BENCH:-0}" == "1" ]]; then
    ./scripts/benchmark_formats.sh
else
    echo "[stage1] skipping benchmark_formats.sh (set WITH_BENCH=1 to enable)"
fi
