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

# Free the ~25 GB the benchmark sweep ate on HDFS. The format/codec
# numbers were already captured in output/format_benchmark.csv and the
# plots; the HDFS imports themselves are not consumed downstream. Skip
# this cleanup if benchmark wasn't run (we'd be deleting someone else's
# results — possibly from a previous --with-bench run we want to keep).
if [[ "$WITH_BENCH" == "1" ]]; then
    echo "[main] cleaning up /user/team1/project/benchmark (~25 GB)"
    hdfs dfs -rm -r -f -skipTrash /user/team1/project/benchmark || true
fi

./scripts/stage2.sh

echo "[main] all stages complete."
