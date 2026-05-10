-- q2: Payment format × is_laundering breakdown.
-- Drives a stacked bar showing which formats over/under-represent laundering.
USE team1_projectdb;
DROP TABLE IF EXISTS q2_results;
CREATE TABLE q2_results AS
SELECT
    payment_format,
    is_laundering,
    COUNT(*) AS n
FROM transactions
GROUP BY payment_format, is_laundering;
