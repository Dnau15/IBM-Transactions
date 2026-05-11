-- q19: Currency-pair flow. Per (payment_currency, receiving_currency,
-- is_laundering): transaction count and total amount. The plot uses this
-- to draw a Sankey of the top corridors and to confirm the q13 binary
-- finding at the per-currency-pair resolution.
USE team1_projectdb;
DROP TABLE IF EXISTS q19_results;

CREATE TABLE q19_results AS
SELECT
    payment_currency,
    receiving_currency,
    is_laundering,
    COUNT(*)               AS n,
    SUM(amount_paid)       AS total_amount
FROM transactions
GROUP BY payment_currency, receiving_currency, is_laundering
ORDER BY n DESC;
