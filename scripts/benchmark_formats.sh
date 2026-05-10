#!/usr/bin/env bash
# Stage I deliverable: benchmark Sqoop import format × compression codec
# combinations on the `transactions` table. Records write time, HDFS size,
# and Spark read time. Runs on the cluster (hadoop-01 or any node with
# sqoop + hdfs + spark-submit on PATH).
set -uo pipefail

PSQL_HOST="hadoop-04.uni.innopolis.ru"
PSQL_DB="team1_projectdb"
TEAM="team1"
TABLE="transactions"
BENCH_BASE="project/benchmark"
OUT_CSV="output/format_benchmark.csv"

PASSWORD=$(head -n 1 secrets/.psql.pass)

mkdir -p output
echo "format,codec,write_seconds,size_bytes,read_seconds,status" > "$OUT_CSV"

# Wipe previous benchmark dir on HDFS so re-runs are idempotent.
hdfs dfs -rm -r -f -skipTrash "/user/${TEAM}/${BENCH_BASE}" || true
hdfs dfs -mkdir -p "/user/${TEAM}/${BENCH_BASE}"

run_one() {
    local fmt="$1" codec="$2"
    local fmt_flag dest codec_flags status="ok"
    local write_s="NA" size_b="NA" read_s="NA"

    case "$fmt" in
        avro)    fmt_flag="--as-avrodatafile" ;;
        parquet) fmt_flag="--as-parquetfile" ;;
        *) echo "unknown format $fmt" >&2; return 1 ;;
    esac

    if [[ "$codec" == "none" ]]; then
        codec_flags=""
    else
        codec_flags="--compress --compression-codec=$codec"
    fi

    dest="${BENCH_BASE}/${fmt}_${codec}"
    echo "=========================================================="
    echo "[bench] $fmt × $codec  ->  /user/${TEAM}/${dest}"
    echo "=========================================================="

    hdfs dfs -rm -r -f -skipTrash "/user/${TEAM}/${dest}" || true

    local work_dir
    work_dir="$(mktemp -d)"

    local t0 t1
    t0=$(date +%s.%N)
    if ! sqoop import \
            --connect "jdbc:postgresql://${PSQL_HOST}/${PSQL_DB}" \
            --username "$TEAM" --password "$PASSWORD" \
            --table "$TABLE" \
            $fmt_flag $codec_flags \
            --target-dir "$dest" \
            --outdir "$work_dir" --bindir "$work_dir" \
            --m 1; then
        status="sqoop_failed"
        echo "${fmt},${codec},${write_s},${size_b},${read_s},${status}" >> "$OUT_CSV"
        rm -rf "$work_dir"
        return 0
    fi
    t1=$(date +%s.%N)
    write_s=$(awk -v a="$t1" -v b="$t0" 'BEGIN{printf "%.3f", a-b}')

    size_b=$(hdfs dfs -du -s "/user/${TEAM}/${dest}" | awk '{print $1}')

    if read_s=$(spark-submit \
                    --master yarn --deploy-mode client \
                    --packages org.apache.spark:spark-avro_2.12:3.2.0 \
                    scripts/bench_read.py "$fmt" "/user/${TEAM}/${dest}" 2>/tmp/bench_read.err \
                | tail -1); then
        :
    else
        status="read_failed"
        read_s="NA"
        echo "spark-submit stderr (last 20 lines):"
        tail -20 /tmp/bench_read.err
    fi

    rm -rf "$work_dir"
    echo "${fmt},${codec},${write_s},${size_b},${read_s},${status}" >> "$OUT_CSV"
}

for fmt in avro parquet; do
    for codec in none snappy gzip bzip2; do
        run_one "$fmt" "$codec"
    done
done

echo
echo "Benchmark complete. Results: $OUT_CSV"
column -t -s, "$OUT_CSV"
