-- b15: Account lifetime distribution. For each account, the wall-clock
-- span from its first to its last transaction (in days), and whether
-- it ever appeared in a laundering transaction. Mule accounts are
-- typically short-lived, so this distribution is a behavioural signal.
--
-- Performance note: an earlier version UNION-ALL'd 32M+32M transaction
-- rows then GROUP BY account, which is the same shape that just blew
-- up on the cluster for q15. The rewrite pre-aggregates each side
-- separately (32M -> 2M rows on each side), then merges the two
-- 2M-row aggregations by GROUP BY account (4M rows total to shuffle,
-- not 64M).
USE team1_projectdb;
DROP TABLE IF EXISTS b15_results;

CREATE TABLE b15_results AS
WITH from_agg AS (
    SELECT from_account     AS account,
           MIN(ts)           AS first_ts,
           MAX(ts)           AS last_ts,
           MAX(is_laundering) AS ever_laundering
    FROM transactions
    GROUP BY from_account
),
to_agg AS (
    SELECT to_account       AS account,
           MIN(ts)           AS first_ts,
           MAX(ts)           AS last_ts,
           MAX(is_laundering) AS ever_laundering
    FROM transactions
    GROUP BY to_account
),
per_account AS (
    SELECT
        account,
        MIN(first_ts)        AS first_ts,
        MAX(last_ts)         AS last_ts,
        MAX(ever_laundering) AS ever_laundering
    FROM (
        SELECT account, first_ts, last_ts, ever_laundering FROM from_agg
        UNION ALL
        SELECT account, first_ts, last_ts, ever_laundering FROM to_agg
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
GROUP BY ever_laundering, lifetime_bucket;
