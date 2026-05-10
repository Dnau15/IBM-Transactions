#!/usr/bin/env bash
# Root orchestrator: runs Stage I and Stage II end-to-end. Default skips
# the format/codec benchmark in Stage I (8 sequential sqoops, ~30 min).
# Pass --with-bench to include it.
#
# Usage:
#   bash main.sh                # stages 1 + 2, no benchmark
#   bash main.sh --with-bench   # stages 1 + 2 + benchmark sweep
set -euo pipefail

WITH_BENCH=0
for arg in "$@"; do
    case "$arg" in
        --with-bench) WITH_BENCH=1 ;;
        *) echo "main.sh: unknown arg '$arg'" >&2; exit 2 ;;
    esac
done

export WITH_BENCH

chmod +x scripts/stage1.sh scripts/stage2.sh

./scripts/stage1.sh
./scripts/stage2.sh

echo "[main] all stages complete."
