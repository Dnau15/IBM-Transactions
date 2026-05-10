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
./scripts/benchmark_formats.sh
