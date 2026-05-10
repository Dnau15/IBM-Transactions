-- q6: Pattern type breakdown — number of pattern instances and total
-- transactions per type. Note: HI-Medium has ~75 distinct pattern_type
-- values, more granular than the paper's 8 canonical types.
USE team1_projectdb;
DROP TABLE IF EXISTS q6_results;
CREATE TABLE q6_results AS
SELECT
    pattern_type,
    COUNT(DISTINCT pattern_group) AS n_patterns,
    COUNT(*)                      AS n_transactions
FROM laundering_patterns
GROUP BY pattern_type
ORDER BY n_transactions DESC;
