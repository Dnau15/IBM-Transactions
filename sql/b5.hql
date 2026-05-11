-- b5: Consortium-membership coverage curve. Rank banks by transaction
-- volume; for each transaction record the minimum K such that the
-- transaction is "covered" when the top-K banks are members. Two
-- definitions of coverage:
--   loose  : at least one endpoint is in top-K
--   strict : both endpoints are in top-K
-- The plot cumulates the histogram into a coverage-vs-K curve, separately
-- for legitimate and laundering transactions, so a regulator can pick the
-- smallest consortium that captures (e.g.) 80% of laundering edges.
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
    SELECT bank, total_n,
           ROW_NUMBER() OVER (ORDER BY total_n DESC) AS rnk
    FROM bank_volume
),
tx_cov AS (
    -- For each transaction, the rank of its lower-ranked and its
    -- higher-ranked bank. min_k_loose = K threshold at which loose
    -- coverage kicks in; min_k_strict = K threshold for strict coverage.
    SELECT
        t.is_laundering,
        LEAST(rf.rnk, rt.rnk)    AS min_k_loose,
        GREATEST(rf.rnk, rt.rnk) AS min_k_strict
    FROM transactions t
    LEFT JOIN ranked rf ON t.from_bank = rf.bank
    LEFT JOIN ranked rt ON t.to_bank   = rt.bank
),
unioned AS (
    SELECT is_laundering, 'loose'  AS coverage_type, min_k_loose  AS k FROM tx_cov
    UNION ALL
    SELECT is_laundering, 'strict' AS coverage_type, min_k_strict AS k FROM tx_cov
)
SELECT
    coverage_type,
    is_laundering,
    k,
    COUNT(*) AS n_at_k
FROM unioned
WHERE k IS NOT NULL
GROUP BY coverage_type, is_laundering, k
ORDER BY coverage_type, is_laundering, k;
