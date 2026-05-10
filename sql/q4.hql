-- q4: Cross-bank vs intra-bank ratio, conditional on laundering.
-- Central question for the consortium framing: how much signal lives
-- only in cross-bank flows?
USE team1_projectdb;
DROP TABLE IF EXISTS q4_results;
CREATE TABLE q4_results AS
SELECT
    is_laundering,
    CASE WHEN from_bank = to_bank THEN 'intra' ELSE 'inter' END AS scope,
    COUNT(*) AS n
FROM transactions
GROUP BY is_laundering,
         CASE WHEN from_bank = to_bank THEN 'intra' ELSE 'inter' END;
