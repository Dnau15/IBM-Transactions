#!/usr/bin/env bash
# Stage II step: run sql/q1.hql .. q9.hql via beeline, exporting each
# qN_results table to output/qN.csv.
#
# For each query we build a combined .hql in a tmpfile containing
#   (1) the original DDL from sql/qN.hql (creates qN_results)
#   (2) an INSERT OVERWRITE DIRECTORY block writing qN_results out as
#       comma-delimited rows under /user/team1/project/output/qN/.
# Both run in a single beeline `-f` call. Then `hdfs dfs -getmerge`
# concatenates the HDFS export into a local file and the shell prepends
# the header line.
#
# Why not a second `beeline -e "SELECT * FROM qN_results"`?
# That pattern hangs on this cluster (a second JDBC connection blocks
# in Tez session warmup) and beeline's --silent=true mode pollutes
# stdout with prompt lines, corrupting the CSV anyway.
#
# Usage:
#   bash scripts/run_eda.sh           # all queries
#   bash scripts/run_eda.sh q1 q4 q9  # subset
set -euo pipefail

HS2_URL="jdbc:hive2://hadoop-03.uni.innopolis.ru:10001"
HDFS_OUT_BASE="/user/team1/project/output"

# Column header per query — kept in shell because deriving from beeline
# DESCRIBE would require another JDBC trip and re-introduce the hang
# problem we're fixing.
declare -A HEADERS=(
    [q1]="day,total,laundering,rate"
    [q2]="payment_format,is_laundering,n"
    [q3]="bank,tx_count,laundering_count,laundering_rate"
    [q4]="is_laundering,scope,n"
    [q5]="account,out_deg,in_deg,ever_laundering"
    [q6]="pattern_type,n_patterns,n_transactions"
    [q7]="from_bank,to_bank,n,laundering_n"
    [q8]="bank_id,name,in_transactions,out_transactions,laundering_ratio"
    [q9]="n_banks,n_patterns"
)

# Stage password into a tmpfile and pass via beeline `-w`. Avoids the
# `-p $PASSWORD` form which exposes the password in /proc/$pid/cmdline
# (visible to anyone running `ps`).
PWDFILE=$(mktemp)
chmod 600 "$PWDFILE"
head -n1 secrets/.psql.pass | tr -d '\n' > "$PWDFILE"
trap 'rm -f "$PWDFILE"' EXIT

BEELINE_AUTH=(-u "$HS2_URL" -n team1 -w "$PWDFILE")

mkdir -p output

if (( $# == 0 )); then
    files=( sql/q[1-9].hql )
else
    files=()
    for q in "$@"; do
        f="sql/${q}.hql"
        if [[ -e "$f" ]]; then
            files+=( "$f" )
        else
            echo "[run_eda] WARN: $f not found, skipping"
        fi
    done
fi

for q in "${files[@]}"; do
    name=$(basename "$q" .hql)
    log="output/${name}_run.log"
    csv="output/${name}.csv"
    hdfs_out="${HDFS_OUT_BASE}/${name}"
    header="${HEADERS[$name]:-}"

    echo "=========================================================="
    echo "[run_eda] $name : $q"
    echo "=========================================================="

    if [[ -z "$header" ]]; then
        echo "[run_eda] WARN: no header registered for $name; skipping"
        continue
    fi

    # Idempotent: clean previous HDFS export.
    hdfs dfs -rm -r -f -skipTrash "$hdfs_out" >/dev/null 2>&1 || true

    # Build combined .hql: DDL from sql/qN.hql + the export block.
    combined=$(mktemp)
    {
        cat "$q"
        echo
        echo "INSERT OVERWRITE DIRECTORY '${hdfs_out}'"
        echo "    ROW FORMAT DELIMITED FIELDS TERMINATED BY ','"
        echo "    SELECT * FROM team1_projectdb.${name}_results;"
    } > "$combined"

    if ! beeline "${BEELINE_AUTH[@]}" \
            --hiveconf hive.execution.engine=tez \
            -f "$combined" > "$log" 2>&1; then
        echo "[run_eda] $name FAILED — see $log (last 20 lines):"
        tail -20 "$log"
        rm -f "$combined"
        continue
    fi
    rm -f "$combined"

    # Pull HDFS export -> local CSV with header line.
    tmp="output/${name}.body"
    if ! hdfs dfs -getmerge "$hdfs_out" "$tmp" 2>>"$log"; then
        echo "[run_eda] $name getmerge FAILED — see $log"
        continue
    fi
    {
        echo "$header"
        cat "$tmp"
    } > "$csv"
    rm -f "$tmp"

    rows=$(($(wc -l < "$csv") - 1))
    echo "[run_eda] $name -> $csv ($rows result rows)"
done
