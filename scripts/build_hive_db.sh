#!/usr/bin/env bash
# Stage II step: run sql/db.hql to build the Hive warehouse on top of
# the Sqoop AVRO files + the accounts Parquet load. Uses spark-sql
# against the cluster Hive metastore; falls back to beeline if the
# spark-sql hive integration is unavailable.
set -euo pipefail

PASSWORD=$(head -n1 secrets/.psql.pass)
HS2_URL="jdbc:hive2://hadoop-03.uni.innopolis.ru:10001"
LOG="output/hive_build.log"

mkdir -p output

echo "[build_hive_db] running sql/db.hql ..."
if command -v spark-sql >/dev/null 2>&1; then
    unset PYSPARK_PYTHON PYSPARK_DRIVER_PYTHON VIRTUAL_ENV
    spark-sql \
        --master yarn --deploy-mode client \
        --conf spark.sql.catalogImplementation=hive \
        --conf hive.metastore.uris=thrift://hadoop-02.uni.innopolis.ru:9883 \
        -f sql/db.hql > "$LOG" 2>&1 \
        || { echo "[build_hive_db] spark-sql failed; see $LOG"; tail -40 "$LOG"; exit 1; }
else
    beeline -u "$HS2_URL" -n team1 -p "$PASSWORD" \
            --hiveconf hive.execution.engine=tez \
            -f sql/db.hql > "$LOG" 2>&1 \
        || { echo "[build_hive_db] beeline failed; see $LOG"; tail -40 "$LOG"; exit 1; }
fi

echo "[build_hive_db] done — $LOG (last 20 lines):"
tail -20 "$LOG"
