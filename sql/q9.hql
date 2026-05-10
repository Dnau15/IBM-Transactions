-- q9: Banks per laundering pattern (THE headline chart for justifying
-- the consortium framing). For each pattern_group, count distinct banks
-- in the union of its from_bank and to_bank legs, then bin by that count.
USE team1_projectdb;
DROP TABLE IF EXISTS q9_results;
CREATE TABLE q9_results AS
WITH banks_per_group AS (
    SELECT pattern_group, COUNT(DISTINCT bank) AS n_banks
    FROM (
        SELECT pattern_group, from_bank AS bank FROM laundering_patterns
        UNION ALL
        SELECT pattern_group, to_bank   AS bank FROM laundering_patterns
    ) legs
    GROUP BY pattern_group
)
SELECT
    n_banks,
    COUNT(*) AS n_patterns
FROM banks_per_group
GROUP BY n_banks
ORDER BY n_banks;
