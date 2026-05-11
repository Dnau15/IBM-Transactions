-- q17: Per-account money-velocity. For each (in -> next-out) pair on the
-- same account, compute the wall-clock gap in seconds and bucket into log
-- decades. Single LAG window pass, no self-join. Per-class counts so the
-- plot can compare legitimate vs ever-laundering pass-through times.
USE team1_projectdb;
DROP TABLE IF EXISTS q17_results;

CREATE TABLE q17_results AS
WITH account_events AS (
    SELECT to_account   AS account,
           UNIX_TIMESTAMP(ts) AS t,
           'in'         AS direction,
           is_laundering
    FROM transactions
    UNION ALL
    SELECT from_account AS account,
           UNIX_TIMESTAMP(ts) AS t,
           'out'        AS direction,
           is_laundering
    FROM transactions
),
with_prev AS (
    SELECT
        account,
        t,
        direction,
        is_laundering,
        LAG(t, 1)         OVER (PARTITION BY account ORDER BY t) AS prev_t,
        LAG(direction, 1) OVER (PARTITION BY account ORDER BY t) AS prev_dir
    FROM account_events
),
gaps AS (
    -- Keep only events where the previous event for this account was an
    -- inflow and the current is an outflow. is_laundering tags the OUT.
    SELECT is_laundering, t - prev_t AS gap_sec
    FROM with_prev
    WHERE prev_dir = 'in' AND direction = 'out'
),
binned AS (
    SELECT
        is_laundering,
        CASE
            WHEN gap_sec < 1       THEN -1     -- sub-second
            WHEN gap_sec < 60      THEN  0     -- 1s – 1min
            WHEN gap_sec < 3600    THEN  1     -- 1min – 1h
            WHEN gap_sec < 86400   THEN  2     -- 1h – 1d
            WHEN gap_sec < 604800  THEN  3     -- 1d – 1w
            ELSE                          4    -- 1w+
        END AS decade
    FROM gaps
)
SELECT is_laundering, decade, COUNT(*) AS n
FROM binned
GROUP BY is_laundering, decade
ORDER BY is_laundering, decade;
