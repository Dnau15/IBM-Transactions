-- q11: Transaction amount distribution by class, broken out by
-- payment_currency. Earlier version mixed all currencies as if they
-- were a single number, which is incorrect (JPY, EUR, USD etc. all
-- live in the same bin). The plot side filters to the top currencies
-- and renders one panel per currency, so the per-class shape comparison
-- is honest.
USE team1_projectdb;
DROP TABLE IF EXISTS q11_results;

CREATE TABLE q11_results AS
SELECT
    payment_currency,
    is_laundering,
    log10_bin,
    COUNT(*)                              AS n,
    ROUND(MIN(amount_paid), 2)            AS bin_min,
    ROUND(MAX(amount_paid), 2)            AS bin_max
FROM (
    SELECT
        payment_currency,
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
GROUP BY payment_currency, is_laundering, log10_bin
ORDER BY payment_currency, is_laundering, log10_bin;
