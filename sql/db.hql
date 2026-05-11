-- Stage II warehouse build.
-- Creates team1_projectdb in HDFS at project/hive/warehouse (deliberately
-- separate from project/warehouse where Sqoop landed the AVRO files).
-- Schemas come from the .avsc files Sqoop generated; types are then cast
-- into a partitioned + bucketed Parquet table for EDA.

SET hive.execution.engine=tez;
SET hive.exec.dynamic.partition=true;
SET hive.exec.dynamic.partition.mode=nonstrict;
SET hive.exec.max.dynamic.partitions=1000;
SET hive.exec.max.dynamic.partitions.pernode=200;
SET hive.enforce.bucketing=true;
-- (`hive.local.time.zone` is inert for BIGINT→TIMESTAMP casts in Hive 3.x —
-- we handle the TZ shift explicitly in the INSERT below instead.)

-- Active-window cutoff: the AMLworld simulator stops emitting the legitimate
-- stream around Sept 16; Sept 17-28 contains only the trailing edge of
-- laundering patterns, which makes per-day laundering rates jump from
-- ~0.1% to ~60% (artefact, not behavior — see q1 discussion). We restrict
-- the transactions table to the active window so downstream EDA and Stage III
-- training don't have to remember to filter every time. laundering_patterns
-- is left unfiltered so q6/q9/q14 still see the full pattern catalogue.
SET hivevar:ACTIVE_UNTIL='2022-09-16';

DROP DATABASE IF EXISTS team1_projectdb CASCADE;
CREATE DATABASE team1_projectdb LOCATION 'project/hive/warehouse';
USE team1_projectdb;

-- ---------- External tables over Sqoop AVRO output ---------------------
-- Schemas are read from the .avsc URLs; column list is inferred.
-- Sqoop's Postgres mapping puts TIMESTAMP and NUMERIC in AVRO as STRING,
-- so we cast in the INSERT below.

CREATE EXTERNAL TABLE transactions_raw
STORED AS AVRO
LOCATION 'project/warehouse/transactions'
TBLPROPERTIES ('avro.schema.url'='project/warehouse/avsc/transactions.avsc');

CREATE EXTERNAL TABLE laundering_patterns_raw
STORED AS AVRO
LOCATION 'project/warehouse/laundering_patterns'
TBLPROPERTIES ('avro.schema.url'='project/warehouse/avsc/laundering_patterns.avsc');

-- accounts.csv was loaded directly to Parquet by scripts/load_accounts.py
-- (no Sqoop / AVRO bridge — it's a one-shot CSV import). Column list
-- declared explicitly because spark-sql refuses to infer a schema from
-- the Parquet files at CREATE TABLE time; this matches the StructType
-- in scripts/load_accounts.py.
CREATE EXTERNAL TABLE accounts (
    bank_name      STRING,
    bank_id        BIGINT,
    account_number STRING,
    entity_id      STRING,
    entity_name    STRING
)
STORED AS PARQUET
LOCATION 'project/warehouse/accounts';

-- ---------- Optimized transactions table (partitioned + bucketed) ------

DROP TABLE IF EXISTS transactions;
CREATE TABLE transactions (
    txn_id              BIGINT,
    ts                  TIMESTAMP,
    from_bank           INT,
    from_account        STRING,
    to_bank             INT,
    to_account          STRING,
    amount_received     DECIMAL(20,4),
    receiving_currency  STRING,
    amount_paid         DECIMAL(20,4),
    payment_currency    STRING,
    payment_format      STRING,
    is_laundering       INT
)
PARTITIONED BY (txn_date DATE)
CLUSTERED BY (from_bank) INTO 16 BUCKETS
STORED AS PARQUET
TBLPROPERTIES ('parquet.compression'='SNAPPY');

-- The AVRO `timestamp` field is plain BIGINT (epoch millis), encoded by
-- Sqoop using the cluster JVM's MSK timezone — i.e., "2022-09-01 00:00:00"
-- from Postgres became 1661979600000 ms (Sept 1 00:00 MSK = Aug 31 21:00 UTC).
-- Hive's CAST(BIGINT → TIMESTAMP) interprets the long in UTC and produces
-- "Aug 31 21:00", which falls into the wrong DATE partition. Compensate by
-- adding 3 hours (10,800,000 ms) before extracting the date.
-- Outer WHERE applies the active-window cutoff from ${hivevar:ACTIVE_UNTIL}.
INSERT OVERWRITE TABLE transactions PARTITION (txn_date)
SELECT * FROM (
    SELECT
        txn_id,
        CAST(`timestamp` + 10800000 AS TIMESTAMP)   AS ts,
        from_bank,
        from_account,
        to_bank,
        to_account,
        CAST(amount_received AS DECIMAL(20,4))      AS amount_received,
        receiving_currency,
        CAST(amount_paid AS DECIMAL(20,4))          AS amount_paid,
        payment_currency,
        payment_format,
        CAST(is_laundering AS INT)                  AS is_laundering,
        DATE_ADD('1970-01-01',
                 CAST((`timestamp` + 10800000) DIV 86400000 AS INT)) AS txn_date
    FROM transactions_raw
) t
WHERE txn_date <= ${hivevar:ACTIVE_UNTIL};

-- ---------- Patterns table (managed Parquet, no partitioning) ----------
-- Only ~22k rows; partitioning here would be overkill.

DROP TABLE IF EXISTS laundering_patterns;
CREATE TABLE laundering_patterns (
    pattern_id          BIGINT,
    pattern_group       INT,
    pattern_type        STRING,
    ts                  TIMESTAMP,
    from_bank           INT,
    from_account        STRING,
    to_bank             INT,
    to_account          STRING,
    amount_received     DECIMAL(20,4),
    receiving_currency  STRING,
    amount_paid         DECIMAL(20,4),
    payment_currency    STRING,
    payment_format      STRING,
    is_laundering       INT
)
STORED AS PARQUET
TBLPROPERTIES ('parquet.compression'='SNAPPY');

INSERT OVERWRITE TABLE laundering_patterns
SELECT
    pattern_id,
    pattern_group,
    pattern_type,
    CAST(`timestamp` + 10800000 AS TIMESTAMP)   AS ts,   -- same +3h MSK shift as transactions
    from_bank,
    from_account,
    to_bank,
    to_account,
    CAST(amount_received AS DECIMAL(20,4))      AS amount_received,
    receiving_currency,
    CAST(amount_paid AS DECIMAL(20,4))          AS amount_paid,
    payment_currency,
    payment_format,
    CAST(is_laundering AS INT)                  AS is_laundering
FROM laundering_patterns_raw;

-- ---------- Drop unpartitioned/unbucketed raw tables -------------------
-- Spec §2.6: only optimized tables remain after this step. EXTERNAL means
-- the underlying HDFS data is preserved.

DROP TABLE transactions_raw;
DROP TABLE laundering_patterns_raw;

-- ---------- Sanity checks ----------------------------------------------

SELECT 'transactions row count'          AS check_name, COUNT(*) AS value FROM transactions;
SELECT 'laundering_patterns row count'   AS check_name, COUNT(*) AS value FROM laundering_patterns;
SELECT 'transactions partition count'    AS check_name, COUNT(DISTINCT txn_date) AS value FROM transactions;
SELECT 'transactions distinct from_bank' AS check_name, COUNT(DISTINCT from_bank) AS value FROM transactions;
SELECT 'transactions laundering ratio'   AS check_name,
       ROUND(SUM(is_laundering) * 100.0 / COUNT(*), 4) AS value FROM transactions;
