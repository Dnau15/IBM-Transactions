-- q5: Per-account in-degree and out-degree, with a flag for whether the
-- account ever participated in a laundering transaction.
-- Plot side downsamples — this table can be hundreds of thousands of rows.
USE team1_projectdb;
DROP TABLE IF EXISTS q5_results;
CREATE TABLE q5_results AS
SELECT
    COALESCE(o.account, i.account)                            AS account,
    COALESCE(o.deg, 0)                                        AS out_deg,
    COALESCE(i.deg, 0)                                        AS in_deg,
    GREATEST(COALESCE(o.laund, 0), COALESCE(i.laund, 0))      AS ever_laundering
FROM (
    SELECT from_account AS account,
           COUNT(*)               AS deg,
           MAX(is_laundering)     AS laund
    FROM transactions GROUP BY from_account
) o
FULL OUTER JOIN (
    SELECT to_account   AS account,
           COUNT(*)               AS deg,
           MAX(is_laundering)     AS laund
    FROM transactions GROUP BY to_account
) i ON o.account = i.account;
