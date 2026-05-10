#!/usr/bin/env bash
# Stage II step: run sql/db.hql to build the Hive warehouse.
# Uses beeline against HiveServer2 — spark-sql on this cluster can't
# auto-discover the Hive metastore, so it falls back to a local-fs
# warehouse that YARN executors can't write to.
set -euo pipefail

HS2_URL="jdbc:hive2://hadoop-03.uni.innopolis.ru:10001"
LOG="output/hive_build.log"

mkdir -p output

# Stage password into a tmpfile for beeline `-w` (avoids the `-p`
# form's password leak through /proc/$pid/cmdline).
PWDFILE=$(mktemp)
chmod 600 "$PWDFILE"
head -n1 secrets/.psql.pass | tr -d '\n' > "$PWDFILE"
trap 'rm -f "$PWDFILE"' EXIT

echo "[build_hive_db] running sql/db.hql via beeline ..."
if ! beeline -u "$HS2_URL" -n team1 -w "$PWDFILE" \
        --hiveconf hive.execution.engine=tez \
        -f sql/db.hql > "$LOG" 2>&1; then
    echo "[build_hive_db] beeline failed; see $LOG (last 40 lines):"
    tail -40 "$LOG"
    exit 1
fi

echo "[build_hive_db] done — $LOG (last 20 lines):"
tail -20 "$LOG"
