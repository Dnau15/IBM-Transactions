-- q7b: Bank-pair flow heatmap across the top 500 banks (the previous
-- q7 limits to top 20 for readability with axis labels). q7b renders
-- the broader topology without tick labels so the reader can see the
-- "long tail" of the bank-pair matrix in addition to the dense
-- corridors among the very largest banks.
USE team1_projectdb;
DROP TABLE IF EXISTS q7b_results;

CREATE TABLE q7b_results AS
WITH bank_volume AS (
    SELECT bank, SUM(c) AS total_volume
    FROM (
        SELECT from_bank AS bank, COUNT(*) AS c FROM transactions GROUP BY from_bank
        UNION ALL
        SELECT to_bank   AS bank, COUNT(*) AS c FROM transactions GROUP BY to_bank
    ) legs
    GROUP BY bank
),
ranked AS (
    SELECT bank, total_volume,
           ROW_NUMBER() OVER (ORDER BY total_volume DESC) AS rnk
    FROM bank_volume
),
top_banks AS (
    SELECT bank, rnk FROM ranked WHERE rnk <= 500
)
SELECT
    rf.rnk AS from_rank,
    rt.rnk AS to_rank,
    COUNT(*)             AS n,
    SUM(t.is_laundering) AS laundering_n
FROM transactions t
JOIN top_banks rf ON t.from_bank = rf.bank
JOIN top_banks rt ON t.to_bank   = rt.bank
GROUP BY rf.rnk, rt.rnk;
