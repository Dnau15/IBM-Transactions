-- q11: Transaction amount distribution by class. Buckets amount_paid into
-- log10 decades (bin N == [10^N, 10^(N+1)) ) and counts transactions per
-- bin per is_laundering. Plot side normalises each class to its own total
-- so the shape comparison shows where laundering over/under-represents.
-- Round-number "structuring" peaks (just below 10k, 100k) should be visible
-- in the laundering series if the dataset includes that typology.
USE team1_projectdb;
DROP TABLE IF EXISTS q11_results;

CREATE TABLE q11_results AS
SELECT
    is_laundering,
    CAST(FLOOR(LOG10(CAST(amount_paid AS DOUBLE))) AS INT)        AS log10_bin,
    COUNT(*)                                                      AS n,
    ROUND(MIN(amount_paid), 2)                                    AS bin_min,
    ROUND(MAX(amount_paid), 2)                                    AS bin_max
FROM transactions
WHERE amount_paid > 0
GROUP BY
    is_laundering,
    CAST(FLOOR(LOG10(CAST(amount_paid AS DOUBLE))) AS INT)
ORDER BY is_laundering, log10_bin;
