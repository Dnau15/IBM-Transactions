-- q18: Pattern x bank-scope distribution. For each laundering pattern
-- instance (pattern_group), count distinct banks involved; then a 2D
-- count by (pattern_type, n_banks). q9 collapses across pattern_type;
-- this disaggregates so the plot can show which typologies are
-- intrinsically multi-bank.
USE team1_projectdb;
DROP TABLE IF EXISTS q18_results;

CREATE TABLE q18_results AS
WITH banks_per_group AS (
    SELECT pattern_group,
           MAX(pattern_type)    AS pattern_type,
           COUNT(DISTINCT bank) AS n_banks
    FROM (
        SELECT pattern_group, pattern_type, from_bank AS bank FROM laundering_patterns
        UNION ALL
        SELECT pattern_group, pattern_type, to_bank   AS bank FROM laundering_patterns
    ) legs
    GROUP BY pattern_group
)
SELECT
    pattern_type,
    n_banks,
    COUNT(*) AS n_patterns
FROM banks_per_group
GROUP BY pattern_type, n_banks
ORDER BY pattern_type, n_banks;
