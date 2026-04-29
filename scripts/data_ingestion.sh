PSQL_HOST="hadoop-04.uni.innopolis.ru"
PSQL_DB="team1_projectdb"
TEAM="team1"
HDFS_WAREHOUSE="project/warehouse"
TMP_DIR="$(mktemp -d)"


PASSWORD=$(head -n 1 secrets/.psql.pass)

echo "[List all databases for user team1]"
sqoop list-databases --connect jdbc:postgresql://hadoop-04.uni.innopolis.ru/team1_projectdb --username team1 --password $PASSWORD

echo "[List all tables for user team1]"
sqoop list-tables --connect jdbc:postgresql://hadoop-04.uni.innopolis.ru/team1_projectdb --username team1 --password $PASSWORD

hdfs dfs -rm -r -f -skipTrash "/user/${TEAM}/${HDFS_WAREHOUSE}" || true
hdfs dfs -mkdir -p "/user/${TEAM}/$(dirname "$HDFS_WAREHOUSE")"

sqoop import-all-tables \
    --connect "jdbc:postgresql://${PSQL_HOST}/${PSQL_DB}" \
    --username "$TEAM" \
    --password "$PASSWORD" \
    --compression-codec=snappy --compress \
    --as-avrodatafile \
    --warehouse-dir="$HDFS_WAREHOUSE" \
    --m 1

mkdir -p output
find "$TMP_DIR" -maxdepth 1 \( -name "*.avsc" -o -name "*.java" \) \
    -exec cp -f {} output/ \;

echo "[data_ingestion] HDFS warehouse listing:"
hdfs dfs -ls "/user/${TEAM}/${HDFS_WAREHOUSE}"

echo "[data_ingestion] Output files:"
ls -l output/
