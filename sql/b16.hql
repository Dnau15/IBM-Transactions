-- b16: Hour-of-day distribution by class. Counts of legitimate and
-- laundering transactions at each hour of the day (cluster local
-- timezone). Business question: do launderers prefer specific hours
-- to move money? q12 shows this on a 2D heatmap; b16 reduces to a
-- 1D density so the business reader sees the per-class shape directly.
USE team1_projectdb;
DROP TABLE IF EXISTS b16_results;

CREATE TABLE b16_results AS
SELECT
    HOUR(ts)      AS hour_of_day,
    is_laundering,
    COUNT(*)      AS n
FROM transactions
GROUP BY HOUR(ts), is_laundering
ORDER BY HOUR(ts), is_laundering;
