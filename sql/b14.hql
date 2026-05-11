-- b14: Total USD value moved per canonical laundering pattern type.
-- Only USD-denominated rows are summed; q19 shows the bulk of laundering
-- is USD-on-USD anyway. The plot rolls the 75 raw pattern_type strings
-- up to the 8 canonical types and reports total $ alongside instance
-- count, so business readers can see which typologies move the most
-- money (not just the most rows).
USE team1_projectdb;
DROP TABLE IF EXISTS b14_results;

CREATE TABLE b14_results AS
SELECT
    pattern_type,
    COUNT(*)                      AS n_transactions,
    COUNT(DISTINCT pattern_group) AS n_pattern_instances,
    SUM(amount_paid)              AS total_usd
FROM laundering_patterns
WHERE payment_currency = 'US Dollar'
GROUP BY pattern_type;
