-- Stage IV — reference SQL for Apache Superset's "Data Description" tab.
-- These queries run against the PostgreSQL `team1_projectdb` database on
-- hadoop-04 (the relational source from Stage I). In Superset:
--   SQL Lab → connect to the postgres `team1` datasource → paste a block
--   below → Save as Dataset → drop into the Data Description tab as a
--   chart panel.
--
-- The Hive-side dashboard tables are in sql/stage4_views.hql (run via
-- scripts/stage4.sh through beeline).

-- ----------------------------------------------------------------------
-- 1. Per-table row counts (drives the "Records per table" panel).
-- ----------------------------------------------------------------------
SELECT 'transactions'        AS table_name, COUNT(*) AS n_rows FROM transactions
UNION ALL
SELECT 'laundering_patterns',                COUNT(*)          FROM laundering_patterns;

-- ----------------------------------------------------------------------
-- 2. Column dtypes (drives the "Schema" panel).
-- ----------------------------------------------------------------------
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('transactions', 'laundering_patterns')
ORDER BY table_name, ordinal_position;

-- ----------------------------------------------------------------------
-- 3. Data samples (drives the "Sample rows" panel — first 10 rows each).
-- ----------------------------------------------------------------------
SELECT * FROM transactions        ORDER BY timestamp LIMIT 10;
SELECT * FROM laundering_patterns ORDER BY timestamp LIMIT 10;

-- ----------------------------------------------------------------------
-- 4. Class balance (drives the "Prevalence" big number).
-- ----------------------------------------------------------------------
SELECT
    COUNT(*)                                            AS total_rows,
    SUM(CASE WHEN is_laundering = 1 THEN 1 ELSE 0 END)  AS laundering_rows,
    ROUND(
        100.0 * SUM(CASE WHEN is_laundering = 1 THEN 1 ELSE 0 END) / COUNT(*),
        4
    )                                                   AS laundering_rate_pct
FROM transactions;

-- ----------------------------------------------------------------------
-- 5. Active-window date span (drives "Date range" panel).
-- ----------------------------------------------------------------------
SELECT
    MIN(timestamp) AS earliest_ts,
    MAX(timestamp) AS latest_ts,
    COUNT(DISTINCT (timestamp / 1000 / 86400)) AS distinct_days_in_data
FROM transactions;

-- ----------------------------------------------------------------------
-- 6. Top payment formats and currencies (drives two small "Top N" panels).
-- ----------------------------------------------------------------------
SELECT payment_format, COUNT(*) AS n
FROM transactions
GROUP BY payment_format
ORDER BY n DESC;

SELECT payment_currency, COUNT(*) AS n
FROM transactions
GROUP BY payment_currency
ORDER BY n DESC;

-- ----------------------------------------------------------------------
-- 7. Data cleaning summary (paste into a Superset Markdown panel).
-- ----------------------------------------------------------------------
-- The following normalisations are applied in Stages I → III BEFORE the
-- transactions table reaches Spark ML:
--   1. Sqoop's AVRO `timestamp` is BIGINT epoch-ms encoded in the cluster
--      JVM's MSK timezone. db.hql adds 10,800,000 ms (+3h) before extracting
--      `txn_date` to keep partition assignment correct.
--   2. Active-window filter `txn_date <= '2022-09-16'` excludes the
--      simulator's patterns-only trailing edge (Sept 17-28, where per-day
--      laundering rate jumps from ~0.1% to ~60% — artefact).
--   3. AVRO STRING types for `amount_received` / `amount_paid` cast to
--      DECIMAL(20,4) in db.hql.
--   4. Currencies bucketed to "top-8 + Other" in build_features.py
--      (TOP_CURRENCIES set).
--   5. Negative downsampling 1:20 + class weighting (`weightCol="weight"`)
--      applied ONLY to the training fold of train_models.py. Test and CV
--      validation slices keep the natural ~0.1% imbalance.
