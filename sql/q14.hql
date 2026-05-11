-- q14: Pattern duration distribution. For each pattern_group, compute
-- the wall-clock span from first to last transaction (max-min). Dumps
-- per-pattern rows so the plot can downsample/box-plot by canonical type.
USE team1_projectdb;
DROP TABLE IF EXISTS q14_results;

CREATE TABLE q14_results AS
SELECT
    pattern_group,
    MAX(pattern_type)                                              AS pattern_type,
    UNIX_TIMESTAMP(MAX(ts)) - UNIX_TIMESTAMP(MIN(ts))              AS duration_seconds,
    ROUND((UNIX_TIMESTAMP(MAX(ts)) - UNIX_TIMESTAMP(MIN(ts))) / 3600.0,    2) AS duration_hours,
    ROUND((UNIX_TIMESTAMP(MAX(ts)) - UNIX_TIMESTAMP(MIN(ts))) / 86400.0,   2) AS duration_days
FROM laundering_patterns
GROUP BY pattern_group;
