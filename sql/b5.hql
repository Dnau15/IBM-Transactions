-- b5: Consortium-membership coverage curve. Rank banks by transaction
-- volume; for each transaction record the minimum K such that the
-- transaction is "covered" when the top-K banks are members. Two
-- coverage definitions:
--   loose  : at least one endpoint is in top-K
--   strict : both endpoints are in top-K
-- The plot cumulates the histogram into a coverage-vs-K curve, split
-- by legitimate / laundering, so a regulator can pick the smallest
-- consortium that captures e.g. 80% of laundering volume.
--
-- Performance notes:
--   * an earlier version joined all 32M transaction rows against
--     the per-bank rank table and then grouped a 64M-row UNION ALL.
--     The Tez AM died on that DAG. Pre-aggregating to bank-pair
--     level (~250K rows) before the join fixed the cardinality.
--   * the resulting plan still chained five CTEs in one DAG, which
--     also crashed the AM. This rewrite splits into two CREATE TABLE
--     statements so Tez plans each in its own DAG, the same trick
--     used by b4.hql.
USE team1_projectdb;
DROP TABLE IF EXISTS b5_ranked;
DROP TABLE IF EXISTS b5_results;

CREATE TABLE b5_ranked AS
WITH bank_volume AS (
    SELECT bank, SUM(n) AS total_n
    FROM (
        SELECT from_bank AS bank, COUNT(*) AS n FROM transactions GROUP BY from_bank
        UNION ALL
        SELECT to_bank   AS bank, COUNT(*) AS n FROM transactions GROUP BY to_bank
    ) u
    GROUP BY bank
)
SELECT bank,
       ROW_NUMBER() OVER (ORDER BY total_n DESC) AS rnk
FROM bank_volume;

CREATE TABLE b5_results AS
WITH pair_agg AS (
    -- Compress 32M txns to ~250K (bank-pair x class) before joining
    -- against the rank dim. The rank join only needs to see one row
    -- per (from_bank, to_bank, is_laundering).
    SELECT from_bank, to_bank, is_laundering, COUNT(*) AS n
    FROM transactions
    GROUP BY from_bank, to_bank, is_laundering
),
pair_cov AS (
    SELECT
        p.is_laundering,
        p.n,
        LEAST(rf.rnk, rt.rnk)    AS min_k_loose,
        GREATEST(rf.rnk, rt.rnk) AS min_k_strict
    FROM pair_agg p
    LEFT JOIN b5_ranked rf ON p.from_bank = rf.bank
    LEFT JOIN b5_ranked rt ON p.to_bank   = rt.bank
),
unioned AS (
    SELECT is_laundering, 'loose'  AS coverage_type, min_k_loose  AS k, n FROM pair_cov
    UNION ALL
    SELECT is_laundering, 'strict' AS coverage_type, min_k_strict AS k, n FROM pair_cov
)
SELECT
    coverage_type,
    is_laundering,
    k,
    SUM(n) AS n_at_k
FROM unioned
WHERE k IS NOT NULL
GROUP BY coverage_type, is_laundering, k;
