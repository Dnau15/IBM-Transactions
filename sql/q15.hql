-- q15: Account-degree histograms. Per-account in-degree and out-degree,
-- binned by exact degree value, split by whether the account ever
-- appeared in a laundering transaction (per-direction definition:
-- "ever sent a laundering txn" / "ever received a laundering txn").
--
-- Performance note: the previous version FULL-OUTER-JOINed two
-- per-account aggregations (~2M rows each) and then UNION-ALL'd to
-- 4M rows. That blew up one of the map tasks on the cluster. This
-- version skips the join — each direction is its own GROUP BY of
-- the transactions table, the per-direction ever-laundering label
-- comes from MAX(is_laundering) within the same GROUP BY, and only
-- the small degree histogram crosses the shuffle.
USE team1_projectdb;
DROP TABLE IF EXISTS q15_results;

CREATE TABLE q15_results AS
SELECT
    direction,
    ever_laundering,
    deg,
    COUNT(*) AS n_accounts
FROM (
    SELECT 'out'              AS direction,
           from_account       AS account,
           COUNT(*)           AS deg,
           MAX(is_laundering) AS ever_laundering
    FROM transactions
    GROUP BY from_account
    UNION ALL
    SELECT 'in'               AS direction,
           to_account         AS account,
           COUNT(*)           AS deg,
           MAX(is_laundering) AS ever_laundering
    FROM transactions
    GROUP BY to_account
) per_account
GROUP BY direction, ever_laundering, deg;
