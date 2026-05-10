-- q1: Class balance + temporal stability — laundering rate by day.
USE team1_projectdb;
DROP TABLE IF EXISTS q1_results;
CREATE TABLE q1_results AS
SELECT
    txn_date AS day,
    COUNT(*) AS total,
    SUM(is_laundering) AS laundering,
    ROUND(SUM(is_laundering) * 1.0 / COUNT(*), 6) AS rate
FROM transactions
GROUP BY txn_date
ORDER BY txn_date;
