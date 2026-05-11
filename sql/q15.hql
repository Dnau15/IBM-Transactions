-- q15: Account in-degree and out-degree histograms, partitioned by whether
-- the account ever appeared in a laundering transaction. q5 scatters a 50K
-- sample; this aggregation keeps the full ~2M accounts and ships only the
-- per-degree counts so the plot can render a CCDF without a downsample.
USE team1_projectdb;
DROP TABLE IF EXISTS q15_results;

CREATE TABLE q15_results AS
WITH per_account AS (
    SELECT
        COALESCE(o.account, i.account)                       AS account,
        COALESCE(o.deg, 0)                                   AS out_deg,
        COALESCE(i.deg, 0)                                   AS in_deg,
        GREATEST(COALESCE(o.laund, 0), COALESCE(i.laund, 0)) AS ever_laundering
    FROM (
        SELECT from_account AS account,
               COUNT(*)               AS deg,
               MAX(is_laundering)     AS laund
        FROM transactions GROUP BY from_account
    ) o
    FULL OUTER JOIN (
        SELECT to_account AS account,
               COUNT(*)             AS deg,
               MAX(is_laundering)   AS laund
        FROM transactions GROUP BY to_account
    ) i ON o.account = i.account
)
SELECT
    direction,
    ever_laundering,
    deg,
    COUNT(*) AS n_accounts
FROM (
    SELECT 'out' AS direction, ever_laundering, out_deg AS deg FROM per_account
    UNION ALL
    SELECT 'in'  AS direction, ever_laundering, in_deg  AS deg FROM per_account
) u
GROUP BY direction, ever_laundering, deg
ORDER BY direction, ever_laundering, deg;
