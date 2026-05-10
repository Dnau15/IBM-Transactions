#!/usr/bin/env bash
# Stage II step: run sql/q1.hql ... q9.hql via spark-sql, then export
# each qN_results table to output/qN.csv via beeline (cleanest CSV
# emission for a managed table).
#
# Usage:
#   bash scripts/run_eda.sh             # all queries
#   bash scripts/run_eda.sh q1 q4 q9    # just these
set -euo pipefail

PASSWORD=$(head -n1 secrets/.psql.pass)
HS2_URL="jdbc:hive2://hadoop-03.uni.innopolis.ru:10001"

mkdir -p output

if (( $# == 0 )); then
    files=( sql/q[1-9].hql )
else
    files=()
    for q in "$@"; do
        f="sql/${q}.hql"
        [[ -e "$f" ]] && files+=( "$f" ) || echo "[run_eda] WARN: $f not found, skipping"
    done
fi

for q in "${files[@]}"; do
    name=$(basename "$q" .hql)
    log="output/${name}_run.log"
    csv="output/${name}.csv"

    echo "=========================================================="
    echo "[run_eda] $name : $q"
    echo "=========================================================="

    # Run the .hql via beeline so DDL hits HiveServer2's metastore (the
    # same one build_hive_db.sh used). spark-sql can't auto-discover the
    # HMS on this cluster — using it here would create qN_results in a
    # local catalog beeline can't see.
    if ! beeline -u "$HS2_URL" -n team1 -p "$PASSWORD" \
            --hiveconf hive.execution.engine=tez \
            -f "$q" > "$log" 2>&1; then
        echo "[run_eda] $name DDL FAILED — see $log"
        tail -20 "$log"
        continue
    fi

    if ! beeline -u "$HS2_URL" -n team1 -p "$PASSWORD" \
            --silent=true --outputformat=csv2 \
            -e "USE team1_projectdb; SELECT * FROM ${name}_results" \
            > "$csv" 2>>"$log"; then
        echo "[run_eda] $name CSV EXPORT FAILED — see $log"
        tail -20 "$log"
        continue
    fi

    rows=$(($(wc -l < "$csv") - 1))
    echo "[run_eda] $name -> $csv ($rows result rows)"
done
