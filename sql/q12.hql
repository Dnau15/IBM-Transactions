-- q12: Laundering rate by hour-of-day × day-of-week.
-- Filtered to Sept 1-16 (the "active" legitimate-stream window) — without
-- this filter, the laundering-only tail of Sept 17-28 (see q1 discussion)
-- skews every hour bin into the 50-65% range.
-- DAYOFWEEK returns 1=Sunday..7=Saturday in Hive 3.x; plot side reorders
-- the rows so Monday appears first.
USE team1_projectdb;
DROP TABLE IF EXISTS q12_results;

CREATE TABLE q12_results AS
SELECT
    HOUR(ts)                                                       AS hour_of_day,
    DAYOFWEEK(ts)                                                  AS day_of_week,
    COUNT(*)                                                       AS total,
    SUM(is_laundering)                                             AS laundering,
    ROUND(SUM(is_laundering) * 1.0 / COUNT(*), 6)                  AS rate
FROM transactions
WHERE txn_date <= '2022-09-16'
GROUP BY HOUR(ts), DAYOFWEEK(ts)
ORDER BY day_of_week, hour_of_day;
