-- q13: Currency mismatch rate (payment_currency vs receiving_currency).
-- Cross-currency transactions are a known FX-layering signal in AML —
-- launderers introduce currency hops to obscure provenance. If the
-- AMLworld simulator calibrates this typology, "mismatch" share will be
-- meaningfully higher among is_laundering=1 than among legitimate flow.
USE team1_projectdb;
DROP TABLE IF EXISTS q13_results;

CREATE TABLE q13_results AS
SELECT
    is_laundering,
    CASE WHEN payment_currency = receiving_currency
         THEN 'same' ELSE 'mismatch' END                          AS currency_scope,
    COUNT(*)                                                      AS n
FROM transactions
GROUP BY
    is_laundering,
    CASE WHEN payment_currency = receiving_currency
         THEN 'same' ELSE 'mismatch' END;
