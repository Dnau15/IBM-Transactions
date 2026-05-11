-- b5: Consortium-membership coverage curve. Rank banks by transaction
-- volume; for each transaction record the minimum K such that the
-- transaction is "covered" when the top-K banks are members. Two
-- definitions:
--   loose  : at least one endpoint is in top-K
--   strict : both endpoints are in top-K
-- The plot cumulates the histogram into a coverage-vs-K curve, split
-- by legitimate / laundering, so a regulator can pick the smallest
-- consortium that captures e.g. 80% of laundering volume.
--
-- Performance note: an earlier version of this query joined all 32M
-- transaction rows directly against the per-bank rank table and then
-- grouped a 64M-row UNION ALL — the Tez AM ran out of memory at
-- shuffle time. The rewrite pre-aggregates by (from_bank, to_bank,
-- is_laundering) first (down to ~250K rows), then joins, then groups.
USE team1_projectdb;
DROP TABLE IF EXISTS b5_results;

CREATE TABLE b5_results AS
WITH bank_volume AS (
    SELECT bank, SUM(n) AS total_n
    FROM (
        SELECT from_bank AS bank, COUNT(*) AS n FROM transactions GROUP BY from_bank
        UNION ALL
        SELECT to_bank   AS bank, COUNT(*) AS n FROM transactions GROUP BY to_bank
    ) u
    GROUP BY bank
),
ranked AS (
    SELECT bank,
           ROW_NUMBER() OVER (ORDER BY total_n DESC) AS rnk
    FROM bank_volume
),
-- Pre-aggregate transactions by (from_bank, to_bank, is_laundering).
-- This shrinks the operand of the rank-join from ~32M rows to at
-- most ~250K (number of distinct bank-pair x class combinations).
pair_agg AS (
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
    LEFT JOIN ranked rf ON p.from_bank = rf.bank
    LEFT JOIN ranked rt ON p.to_bank   = rt.bank
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
GROUP BY coverage_type, is_laundering, k
ORDER BY coverage_type, is_laundering, k;
