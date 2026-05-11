-- b15: Account lifetime distribution. For each account, the wall-clock
-- span from its first to its last transaction (in days), and whether
-- it ever appeared in a laundering transaction. Mule accounts are
-- typically short-lived and rapidly cycle through funds, so an
-- ever-laundering vs legitimate-only comparison on this axis is a
-- business-grade behavioural signal.
USE team1_projectdb;
DROP TABLE IF EXISTS b15_results;

CREATE TABLE b15_results AS
WITH per_account AS (
    SELECT account, MAX(ts) AS last_ts, MIN(ts) AS first_ts,
           MAX(is_laundering) AS ever_laundering
    FROM (
        SELECT from_account AS account, ts, is_laundering FROM transactions
        UNION ALL
        SELECT to_account   AS account, ts, is_laundering FROM transactions
    ) u
    GROUP BY account
),
binned AS (
    SELECT
        ever_laundering,
        CASE
            WHEN (UNIX_TIMESTAMP(last_ts) - UNIX_TIMESTAMP(first_ts)) / 86400.0 < 1   THEN 0
            WHEN (UNIX_TIMESTAMP(last_ts) - UNIX_TIMESTAMP(first_ts)) / 86400.0 < 2   THEN 1
            WHEN (UNIX_TIMESTAMP(last_ts) - UNIX_TIMESTAMP(first_ts)) / 86400.0 < 4   THEN 2
            WHEN (UNIX_TIMESTAMP(last_ts) - UNIX_TIMESTAMP(first_ts)) / 86400.0 < 7   THEN 3
            WHEN (UNIX_TIMESTAMP(last_ts) - UNIX_TIMESTAMP(first_ts)) / 86400.0 < 11  THEN 4
            WHEN (UNIX_TIMESTAMP(last_ts) - UNIX_TIMESTAMP(first_ts)) / 86400.0 < 14  THEN 5
            ELSE                                                                          6
        END AS lifetime_bucket
    FROM per_account
)
SELECT
    ever_laundering,
    lifetime_bucket,
    COUNT(*) AS n_accounts
FROM binned
GROUP BY ever_laundering, lifetime_bucket
ORDER BY ever_laundering, lifetime_bucket;
