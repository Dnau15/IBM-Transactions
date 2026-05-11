-- q10: Top 20 banks by total transaction volume (incoming + outgoing).
-- Self-contained (does not reference q8_results) so query order doesn't matter.
USE team1_projectdb;
DROP TABLE IF EXISTS q10_results;

CREATE TABLE q10_results AS
WITH bank_names AS (
    SELECT bank_id, MIN(bank_name) AS bank_name
    FROM accounts GROUP BY bank_id
),
out_m AS (
    SELECT from_bank             AS bank_id,
           COUNT(*)              AS out_tx,
           SUM(is_laundering)    AS out_laund
    FROM transactions GROUP BY from_bank
),
in_m AS (
    SELECT to_bank               AS bank_id,
           COUNT(*)              AS in_tx,
           SUM(is_laundering)    AS in_laund
    FROM transactions GROUP BY to_bank
)
SELECT
    COALESCE(o.bank_id, i.bank_id)                                AS bank_id,
    bn.bank_name                                                  AS name,
    COALESCE(i.in_tx, 0)                                          AS in_transactions,
    COALESCE(o.out_tx, 0)                                         AS out_transactions,
    COALESCE(i.in_tx, 0) + COALESCE(o.out_tx, 0)                  AS total_tx,
    ROUND(
        (COALESCE(o.out_laund, 0) + COALESCE(i.in_laund, 0)) * 1.0
        / NULLIF(COALESCE(o.out_tx, 0) + COALESCE(i.in_tx, 0), 0),
        6
    )                                                             AS laundering_ratio
FROM out_m o
FULL OUTER JOIN in_m i ON o.bank_id = i.bank_id
LEFT JOIN bank_names bn ON bn.bank_id = COALESCE(o.bank_id, i.bank_id)
ORDER BY total_tx DESC
LIMIT 20;
