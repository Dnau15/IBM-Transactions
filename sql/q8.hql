-- q8: Per-bank laundering metrics. Joins the accounts dim table (loaded
-- via scripts/load_accounts.py) to attach a human-readable bank name to
-- each bank_id seen in transactions. Plots downstream sort this by
-- laundering_ratio (DESC for top-risk banks; ASC for cleanest banks).
USE team1_projectdb;
DROP TABLE IF EXISTS q8_results;

CREATE TABLE q8_results AS
WITH bank_names AS (
    -- Multiple accounts per bank in accounts.csv; take any name per bank_id.
    SELECT bank_id, MIN(bank_name) AS bank_name
    FROM accounts
    GROUP BY bank_id
),
out_m AS (
    SELECT from_bank             AS bank_id,
           COUNT(*)              AS out_transactions,
           SUM(is_laundering)    AS out_laundering
    FROM transactions
    GROUP BY from_bank
),
in_m AS (
    SELECT to_bank               AS bank_id,
           COUNT(*)              AS in_transactions,
           SUM(is_laundering)    AS in_laundering
    FROM transactions
    GROUP BY to_bank
)
SELECT
    COALESCE(o.bank_id, i.bank_id)                                AS bank_id,
    bn.bank_name                                                  AS name,
    COALESCE(i.in_transactions, 0)                                AS in_transactions,
    COALESCE(o.out_transactions, 0)                               AS out_transactions,
    ROUND(
        (COALESCE(o.out_laundering, 0) + COALESCE(i.in_laundering, 0)) * 1.0
        / NULLIF(COALESCE(o.out_transactions, 0) + COALESCE(i.in_transactions, 0), 0),
        6
    )                                                             AS laundering_ratio
FROM out_m o
FULL OUTER JOIN in_m i ON o.bank_id = i.bank_id
LEFT JOIN bank_names bn ON bn.bank_id = COALESCE(o.bank_id, i.bank_id)
ORDER BY laundering_ratio DESC;
