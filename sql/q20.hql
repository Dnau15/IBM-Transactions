-- q20: Top bank-pair flows with laundering enrichment. q7 is a 20x20
-- heatmap of log counts; this returns ranked rows so the plot can name
-- individual corridors. Filter out near-empty pairs so the ratio is
-- meaningful.
USE team1_projectdb;
DROP TABLE IF EXISTS q20_results;

CREATE TABLE q20_results AS
SELECT
    from_bank,
    to_bank,
    COUNT(*)               AS n_total,
    SUM(is_laundering)     AS n_laundering,
    SUM(is_laundering) * 1.0 / COUNT(*) AS laundering_rate
FROM transactions
GROUP BY from_bank, to_bank
HAVING COUNT(*) >= 1000
ORDER BY n_total DESC;
