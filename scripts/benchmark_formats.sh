#!/usr/bin/env bash
# Stage I deliverable: benchmark Sqoop import format × compression codec
# combinations on the `transactions` table. Records write time, HDFS size,
# Spark read time, and a status column.
#
# Resumable: if an HDFS target directory already has _SUCCESS, sqoop is
# skipped and only the read measurement runs (write_seconds = "cached").
# Set RESET=1 to wipe HDFS benchmark dirs and start fresh.
set -uo pipefail

PSQL_HOST="hadoop-04.uni.innopolis.ru"
PSQL_DB="team1_projectdb"
TEAM="team1"
TABLE="transactions"
BENCH_BASE="project/benchmark"
OUT_CSV="output/format_benchmark.csv"

PASSWORD=$(head -n 1 secrets/.psql.pass)

# Spark on this cluster ships its own Python with pyspark. If a venv was
# sourced earlier (data_collection.sh), PYSPARK_PYTHON / VIRTUAL_ENV may be
# set in the parent shell and point at a Python without pyspark — which
# makes spark-submit shut down silently within ~300 ms (no SparkContext,
# no traceback). Strip those vars so spark-submit picks up the system one.
unset PYSPARK_PYTHON PYSPARK_DRIVER_PYTHON VIRTUAL_ENV

mkdir -p output

if [[ "${RESET:-0}" == "1" ]]; then
    echo "[bench] RESET=1 — wiping HDFS benchmark dirs"
    hdfs dfs -rm -r -f -skipTrash "/user/${TEAM}/${BENCH_BASE}" || true
fi

hdfs dfs -mkdir -p "/user/${TEAM}/${BENCH_BASE}"

echo "format,codec,effective_codec,write_seconds,size_bytes,read_seconds,status" > "$OUT_CSV"

# Avro names its zlib/gzip codec "deflate". Same algorithm — we just
# translate the spec's requested name to what Avro accepts.
effective_codec_for() {
    local fmt="$1" codec="$2"
    if [[ "$fmt" == "avro" && "$codec" == "gzip" ]]; then
        echo "deflate"
    else
        echo "$codec"
    fi
}

is_unsupported() {
    local fmt="$1" codec="$2"
    # Parquet's CompressionCodecName enum has no BZIP2 entry.
    [[ "$fmt" == "parquet" && "$codec" == "bzip2" ]]
}

run_one() {
    local fmt="$1" codec="$2"
    local effective_codec; effective_codec=$(effective_codec_for "$fmt" "$codec")
    local fmt_flag codec_flags dest
    local write_s="NA" size_b="NA" read_s="NA" status="ok"

    echo "=========================================================="
    echo "[bench] $fmt × $codec  (effective: $effective_codec)"
    echo "=========================================================="

    if is_unsupported "$fmt" "$codec"; then
        echo "[bench] $fmt does not support $codec — recording as codec_unsupported"
        echo "${fmt},${codec},N/A,NA,NA,NA,codec_unsupported" >> "$OUT_CSV"
        return 0
    fi

    case "$fmt" in
        avro)    fmt_flag="--as-avrodatafile" ;;
        parquet) fmt_flag="--as-parquetfile" ;;
        *) echo "unknown format $fmt" >&2; return 1 ;;
    esac

    if [[ "$effective_codec" == "none" ]]; then
        codec_flags=""
    else
        codec_flags="--compress --compression-codec=$effective_codec"
    fi

    dest="${BENCH_BASE}/${fmt}_${codec}"

    # Resumable: skip sqoop if a successful import already lives here.
    if hdfs dfs -test -e "/user/${TEAM}/${dest}/_SUCCESS" 2>/dev/null; then
        echo "[bench] /user/${TEAM}/${dest}/_SUCCESS exists — skipping sqoop import"
        write_s="cached"
    else
        # Clean any partial state from a previously failed run.
        hdfs dfs -rm -r -f -skipTrash "/user/${TEAM}/${dest}" || true
        local work_dir; work_dir="$(mktemp -d)"
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
            echo "${fmt},${codec},${effective_codec},NA,NA,NA,${status}" >> "$OUT_CSV"
            rm -rf "$work_dir"
            return 0
        fi
        t1=$(date +%s.%N)
        write_s=$(awk -v a="$t1" -v b="$t0" 'BEGIN{printf "%.3f", a-b}')
        rm -rf "$work_dir"
    fi

    size_b=$(hdfs dfs -du -s "/user/${TEAM}/${dest}" | awk '{print $1}')

    # Read benchmark — full stdout/stderr per combo so failures are diagnosable.
    local out_log="output/bench_read_${fmt}_${codec}.out"
    local err_log="output/bench_read_${fmt}_${codec}.err"

    if spark-submit \
            --master yarn --deploy-mode client \
            --packages org.apache.spark:spark-avro_2.12:3.2.4 \
            scripts/bench_read.py "$fmt" "/user/${TEAM}/${dest}" \
            >"$out_log" 2>"$err_log"; then
        read_s=$(tail -n1 "$out_log" | tr -d '[:space:]')
        if ! awk -v x="$read_s" 'BEGIN{exit !(x+0==x && x+0>0)}' 2>/dev/null; then
            status="read_no_output"
            read_s="NA"
            echo "[bench] read produced no numeric output; see $out_log / $err_log"
        fi
    else
        status="read_failed"
        read_s="NA"
        echo "[bench] spark-submit exited non-zero — see $err_log"
        echo "[bench] last 30 lines of stderr:"
        tail -n30 "$err_log"
    fi

    echo "${fmt},${codec},${effective_codec},${write_s},${size_b},${read_s},${status}" >> "$OUT_CSV"
}

for fmt in avro parquet; do
    for codec in none snappy gzip bzip2; do
        run_one "$fmt" "$codec"
    done
done

echo
echo "Benchmark complete. Results: $OUT_CSV"
column -t -s, "$OUT_CSV"
