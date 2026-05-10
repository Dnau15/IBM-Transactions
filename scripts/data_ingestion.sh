#!/usr/bin/env bash
set -euo pipefail

PSQL_HOST="hadoop-04.uni.innopolis.ru"
PSQL_DB="team1_projectdb"
TEAM="team1"
HDFS_WAREHOUSE="project/warehouse"

PASSWORD=$(head -n 1 secrets/.psql.pass)

mkdir -p output

echo "[List all databases for user team1]"
sqoop list-databases \
    --connect "jdbc:postgresql://${PSQL_HOST}/${PSQL_DB}" \
    --username "$TEAM" --password "$PASSWORD"

echo "[List all tables for user team1]"
sqoop list-tables \
    --connect "jdbc:postgresql://${PSQL_HOST}/${PSQL_DB}" \
    --username "$TEAM" --password "$PASSWORD"

# Clean previous warehouse contents (idempotent re-runs).
hdfs dfs -rm -r -f -skipTrash "/user/${TEAM}/${HDFS_WAREHOUSE}" || true
hdfs dfs -mkdir -p "/user/${TEAM}/$(dirname "$HDFS_WAREHOUSE")"

# Run sqoop from a scratch dir so codegen artifacts don't pollute the repo,
# then copy them back into output/ where Stage II expects them.
WORK_DIR="$(mktemp -d)"
pushd "$WORK_DIR" > /dev/null

sqoop import-all-tables \
    --connect "jdbc:postgresql://${PSQL_HOST}/${PSQL_DB}" \
    --username "$TEAM" \
    --password "$PASSWORD" \
    --compression-codec=snappy --compress \
    --as-avrodatafile \
    --warehouse-dir="$HDFS_WAREHOUSE" \
    --outdir "$WORK_DIR" \
    --bindir "$WORK_DIR" \
    --m 1

popd > /dev/null

find "$WORK_DIR" -maxdepth 1 \( -name "*.avsc" -o -name "*.java" \) \
    -exec cp -f {} output/ \;

echo "[data_ingestion] HDFS warehouse listing:"
hdfs dfs -ls "/user/${TEAM}/${HDFS_WAREHOUSE}"

echo "[data_ingestion] Output files:"
ls -l output/
