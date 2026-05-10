-- q3: Bank size distribution — counts a transaction toward both endpoints
-- so the histogram captures total bank activity (not just outgoing).
USE team1_projectdb;
DROP TABLE IF EXISTS q3_results;
CREATE TABLE q3_results AS
SELECT
    bank,
    SUM(c) AS tx_count,
    SUM(l) AS laundering_count,
    ROUND(SUM(l) * 1.0 / SUM(c), 6) AS laundering_rate
FROM (
    SELECT from_bank AS bank,
           COUNT(*)         AS c,
           SUM(is_laundering) AS l
    FROM transactions GROUP BY from_bank
    UNION ALL
    SELECT to_bank   AS bank,
           COUNT(*)         AS c,
           SUM(is_laundering) AS l
    FROM transactions GROUP BY to_bank
) all_legs
GROUP BY bank
ORDER BY tx_count DESC;
