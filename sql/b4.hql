-- b4: Pattern visibility per data-sharing setup. For each pattern_group:
--   isolated_visible_edges     edges seen by the SINGLE bank that holds
--                              the largest share of this pattern's legs
--   loose_consortium_edges     edges with >=1 endpoint in the top-20
--                              banks by total volume
--   strict_consortium_edges    edges with BOTH endpoints in the top-20
-- The plot rolls these per-instance counts up to the 8 canonical types
-- and reports the average fraction of edges visible to each setup.
USE team1_projectdb;
DROP TABLE IF EXISTS b4_results;

CREATE TABLE b4_results AS
WITH bank_volume AS (
    SELECT bank, SUM(n) AS total_n
    FROM (
        SELECT from_bank AS bank, COUNT(*) AS n FROM transactions GROUP BY from_bank
        UNION ALL
        SELECT to_bank   AS bank, COUNT(*) AS n FROM transactions GROUP BY to_bank
    ) u
    GROUP BY bank
),
top_banks AS (
    SELECT bank FROM bank_volume ORDER BY total_n DESC LIMIT 20
),
edges_at_bank AS (
    -- Edge count of each pattern visible to each bank touching it.
    -- For an intra-bank edge (from = to), the bank still sees it
    -- exactly once: the second UNION arm's WHERE clause skips the
    -- to-side row when both endpoints are the same bank.
    SELECT pattern_group, bank, COUNT(*) AS n_visible
    FROM (
        SELECT pattern_group, from_bank AS bank
        FROM laundering_patterns
        UNION ALL
        SELECT pattern_group, to_bank AS bank
        FROM laundering_patterns
        WHERE from_bank <> to_bank
    ) u
    GROUP BY pattern_group, bank
),
isolated_per_pattern AS (
    SELECT pattern_group, MAX(n_visible) AS isolated_visible_edges
    FROM edges_at_bank
    GROUP BY pattern_group
),
consortium_per_pattern AS (
    SELECT
        lp.pattern_group,
        SUM(CASE WHEN tbf.bank IS NOT NULL OR  tbt.bank IS NOT NULL THEN 1 ELSE 0 END) AS loose_consortium_edges,
        SUM(CASE WHEN tbf.bank IS NOT NULL AND tbt.bank IS NOT NULL THEN 1 ELSE 0 END) AS strict_consortium_edges
    FROM laundering_patterns lp
    LEFT JOIN top_banks tbf ON lp.from_bank = tbf.bank
    LEFT JOIN top_banks tbt ON lp.to_bank   = tbt.bank
    GROUP BY lp.pattern_group
),
pattern_size AS (
    SELECT pattern_group, MAX(pattern_type) AS pattern_type, COUNT(*) AS n_edges_total
    FROM laundering_patterns
    GROUP BY pattern_group
)
SELECT
    p.pattern_group,
    p.pattern_type,
    p.n_edges_total,
    i.isolated_visible_edges,
    c.loose_consortium_edges,
    c.strict_consortium_edges
FROM pattern_size p
JOIN isolated_per_pattern  i ON p.pattern_group = i.pattern_group
JOIN consortium_per_pattern c ON p.pattern_group = c.pattern_group;
