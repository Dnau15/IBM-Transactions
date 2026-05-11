-- b1: Sub-threshold structuring histogram. Fine-grained $50 bins on the
-- $7,000–$12,000 amount range, conditioned on class. Tests whether
-- AMLworld's synthetic structuring leaves a visible signature just below
-- the regulatory $10K CTR threshold (FFIEC Appendix G).
USE team1_projectdb;
DROP TABLE IF EXISTS b1_results;

CREATE TABLE b1_results AS
SELECT
    is_laundering,
    CAST(FLOOR(amount_paid / 50) * 50 AS INT) AS bin_lo,
    COUNT(*) AS n
FROM transactions
WHERE amount_paid BETWEEN 7000 AND 12000
GROUP BY is_laundering, CAST(FLOOR(amount_paid / 50) * 50 AS INT)
ORDER BY is_laundering, bin_lo;
