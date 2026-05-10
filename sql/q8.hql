-- q8: Consortium coverage curve. For K members ∈ {3, 5, 10, 20}, count
-- transactions where BOTH endpoints are within the top-K banks (proper
-- consortium semantics — boundary transactions to non-members don't
-- count). Output also has the totals so plotting can derive ratios.
USE team1_projectdb;
DROP TABLE IF EXISTS q8_results;
CREATE TABLE q8_results AS
WITH bank_volume AS (
    SELECT bank, SUM(c) AS volume
    FROM (
        SELECT from_bank AS bank, COUNT(*) AS c FROM transactions GROUP BY from_bank
        UNION ALL
        SELECT to_bank   AS bank, COUNT(*) AS c FROM transactions GROUP BY to_bank
    ) legs
    GROUP BY bank
),
ranked AS (
    SELECT bank, ROW_NUMBER() OVER (ORDER BY volume DESC) AS rank
    FROM bank_volume
),
joined AS (
    SELECT
        t.is_laundering,
        fr.rank AS from_rank,
        tr.rank AS to_rank
    FROM transactions t
    LEFT JOIN ranked fr ON t.from_bank = fr.bank
    LEFT JOIN ranked tr ON t.to_bank   = tr.bank
),
ks AS (
    SELECT 3 AS k UNION ALL SELECT 5 UNION ALL SELECT 10 UNION ALL SELECT 20
)
SELECT
    ks.k                                                       AS k,
    SUM(CASE WHEN j.from_rank <= ks.k AND j.to_rank <= ks.k
             THEN 1 ELSE 0 END)                                 AS tx_in_consortium,
    COUNT(*)                                                    AS tx_total,
    SUM(CASE WHEN j.from_rank <= ks.k AND j.to_rank <= ks.k
                  AND j.is_laundering = 1 THEN 1 ELSE 0 END)    AS laundering_in_consortium,
    SUM(j.is_laundering)                                        AS laundering_total
FROM joined j
CROSS JOIN ks
GROUP BY ks.k
ORDER BY ks.k;
