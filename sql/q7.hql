-- q7: Bank-pair flow heatmap — top 20 banks by total transaction count
-- (incoming + outgoing summed), then per-pair tx counts and laundering counts.
USE team1_projectdb;
DROP TABLE IF EXISTS q7_results;
CREATE TABLE q7_results AS
WITH bank_volume AS (
    SELECT bank, SUM(c) AS total_volume
    FROM (
        SELECT from_bank AS bank, COUNT(*) AS c FROM transactions GROUP BY from_bank
        UNION ALL
        SELECT to_bank   AS bank, COUNT(*) AS c FROM transactions GROUP BY to_bank
    ) legs
    GROUP BY bank
),
top_banks AS (
    SELECT bank
    FROM bank_volume
    ORDER BY total_volume DESC
    LIMIT 20
)
SELECT
    t.from_bank,
    t.to_bank,
    COUNT(*)             AS n,
    SUM(t.is_laundering) AS laundering_n
FROM transactions t
JOIN top_banks f ON t.from_bank = f.bank
JOIN top_banks z ON t.to_bank   = z.bank
GROUP BY t.from_bank, t.to_bank;
