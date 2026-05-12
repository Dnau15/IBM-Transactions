-- Stage IV — supporting Hive views for Tab 1 (Data Description) of the
-- Apache Superset dashboard.
--
-- The Stage IV rubric requires Tab 1 to surface:
--   * number of records per table
--   * column datatypes (queryable via SQL)
--   * data samples from tables
--
-- We materialize each of these as a Hive VIEW so Superset can register
-- them as datasets without SQL Lab. Run with:
--
--   beeline -u jdbc:hive2://hadoop-03.uni.innopolis.ru:10001 \
--           -n team1 -w secrets/.psql.pass \
--           -f sql/db_stats.hql
--
-- Idempotent: every view is dropped before re-creation.

USE team1_projectdb;

-- ---------------------------------------------------------------------------
-- 1. Per-table record counts. One row per base table; feeds the three
--    Big-Number charts at the top of Tab 1. Numbers reflect the active-
--    window cutoff (2022-09-16) applied in sql/db.hql.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS db_stats_per_table;
CREATE VIEW db_stats_per_table AS
SELECT 'transactions'        AS table_name, COUNT(*) AS row_count FROM transactions
UNION ALL
SELECT 'laundering_patterns'                , COUNT(*)            FROM laundering_patterns
UNION ALL
SELECT 'accounts'                           , COUNT(*)            FROM accounts;

-- ---------------------------------------------------------------------------
-- 2. Schemas as queryable views. The rubric phrasing is "column datatypes
--    queryable via SQL" — Hive's DESCRIBE output isn't a relation, so we
--    materialize the schema as a 2-column view per base table.
--
--    Source of truth: the CREATE TABLE statements in sql/db.hql. Keep in
--    sync if those schemas change.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS schema_transactions;
CREATE VIEW schema_transactions AS
SELECT 'txn_id'             AS column_name, 'BIGINT'         AS data_type UNION ALL
SELECT 'ts'                                , 'TIMESTAMP'                  UNION ALL
SELECT 'from_bank'                         , 'INT'                        UNION ALL
SELECT 'from_account'                      , 'STRING'                     UNION ALL
SELECT 'to_bank'                           , 'INT'                        UNION ALL
SELECT 'to_account'                        , 'STRING'                     UNION ALL
SELECT 'amount_received'                   , 'DECIMAL(20,4)'              UNION ALL
SELECT 'receiving_currency'                , 'STRING'                     UNION ALL
SELECT 'amount_paid'                       , 'DECIMAL(20,4)'              UNION ALL
SELECT 'payment_currency'                  , 'STRING'                     UNION ALL
SELECT 'payment_format'                    , 'STRING'                     UNION ALL
SELECT 'is_laundering'                     , 'INT'                        UNION ALL
SELECT 'txn_date'                          , 'DATE (partition)';

DROP VIEW IF EXISTS schema_laundering_patterns;
CREATE VIEW schema_laundering_patterns AS
SELECT 'pattern_id'         AS column_name, 'BIGINT'         AS data_type UNION ALL
SELECT 'pattern_group'                     , 'INT'                        UNION ALL
SELECT 'pattern_type'                      , 'STRING'                     UNION ALL
SELECT 'ts'                                , 'TIMESTAMP'                  UNION ALL
SELECT 'from_bank'                         , 'INT'                        UNION ALL
SELECT 'from_account'                      , 'STRING'                     UNION ALL
SELECT 'to_bank'                           , 'INT'                        UNION ALL
SELECT 'to_account'                        , 'STRING'                     UNION ALL
SELECT 'amount_received'                   , 'DECIMAL(20,4)'              UNION ALL
SELECT 'receiving_currency'                , 'STRING'                     UNION ALL
SELECT 'amount_paid'                       , 'DECIMAL(20,4)'              UNION ALL
SELECT 'payment_currency'                  , 'STRING'                     UNION ALL
SELECT 'payment_format'                    , 'STRING'                     UNION ALL
SELECT 'is_laundering'                     , 'INT';

DROP VIEW IF EXISTS schema_accounts;
CREATE VIEW schema_accounts AS
SELECT 'bank_name'          AS column_name, 'STRING'         AS data_type UNION ALL
SELECT 'bank_id'                           , 'BIGINT'                     UNION ALL
SELECT 'account_number'                    , 'STRING'                     UNION ALL
SELECT 'entity_id'                         , 'STRING'                     UNION ALL
SELECT 'entity_name'                       , 'STRING';

-- ---------------------------------------------------------------------------
-- 3. Data sample views. Five rows per base table. Sample tables are used
--    on Tab 1 to show what real rows look like (rubric: "data samples from
--    tables"). LIMIT 5 inside a view is allowed in Hive 3.x.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS sample_transactions;
CREATE VIEW sample_transactions AS
SELECT * FROM transactions LIMIT 5;

DROP VIEW IF EXISTS sample_laundering_patterns;
CREATE VIEW sample_laundering_patterns AS
SELECT * FROM laundering_patterns LIMIT 5;

DROP VIEW IF EXISTS sample_accounts;
CREATE VIEW sample_accounts AS
SELECT * FROM accounts LIMIT 5;

-- ---------------------------------------------------------------------------
-- 4. Static AML enforcement fines for chart C1 (b8). Loaded from
--    scripts/refs/aml_fines.csv. Materialized as an internal table because
--    Superset's Bar Chart wants a real Hive table, not a markdown CSV.
--
--    Re-run by hand if scripts/refs/aml_fines.csv ever updates.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS b8_fines;
CREATE TABLE b8_fines (
    institution        STRING,
    year               INT,
    fine_usd_billion   DOUBLE,
    authority          STRING,
    note               STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
TBLPROPERTIES ('skip.header.line.count'='1');

LOAD DATA LOCAL INPATH 'scripts/refs/aml_fines.csv' OVERWRITE INTO TABLE b8_fines;
