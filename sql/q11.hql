-- q11: Transaction amount distribution by class.
-- Earlier version used FLOOR(LOG10(amount_paid)) for binning; on Hive 3.x
-- with our DECIMAL(20,4) source that collapsed every row into bin 0 (the
-- ladder approach below sidesteps whatever DECIMAL→DOUBLE/LOG10 quirk
-- caused that and gives explicit, human-readable bin labels).
USE team1_projectdb;
DROP TABLE IF EXISTS q11_results;

CREATE TABLE q11_results AS
SELECT
    is_laundering,
    log10_bin,
    COUNT(*)                              AS n,
    ROUND(MIN(amount_paid), 2)            AS bin_min,
    ROUND(MAX(amount_paid), 2)            AS bin_max
FROM (
    SELECT
        is_laundering,
        amount_paid,
        CASE
            WHEN amount_paid < 1           THEN -1
            WHEN amount_paid < 10          THEN 0
            WHEN amount_paid < 100         THEN 1
            WHEN amount_paid < 1000        THEN 2
            WHEN amount_paid < 10000       THEN 3
            WHEN amount_paid < 100000      THEN 4
            WHEN amount_paid < 1000000     THEN 5
            WHEN amount_paid < 10000000    THEN 6
            WHEN amount_paid < 100000000   THEN 7
            WHEN amount_paid < 1000000000  THEN 8
            ELSE                                9
        END AS log10_bin
    FROM transactions
    WHERE amount_paid > 0
) t
GROUP BY is_laundering, log10_bin
ORDER BY is_laundering, log10_bin;
