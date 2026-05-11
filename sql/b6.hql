-- b6: Cross-bank share by pattern type. For each laundering pattern
-- instance (pattern_group), count intra-bank vs inter-bank edges; then
-- aggregate by pattern_type. Complements q9 (banks-per-pattern,
-- pattern-type-agnostic) with a per-type breakdown of how much of each
-- typology actually crosses bank boundaries.
USE team1_projectdb;
DROP TABLE IF EXISTS b6_results;

CREATE TABLE b6_results AS
WITH per_group AS (
    SELECT
        pattern_group,
        MAX(pattern_type) AS pattern_type,
        SUM(CASE WHEN from_bank = to_bank  THEN 1 ELSE 0 END) AS n_intra_edges,
        SUM(CASE WHEN from_bank <> to_bank THEN 1 ELSE 0 END) AS n_inter_edges
    FROM laundering_patterns
    GROUP BY pattern_group
)
SELECT
    pattern_type,
    COUNT(*)                                                  AS n_patterns,
    SUM(CASE WHEN n_inter_edges > 0 THEN 1 ELSE 0 END)        AS n_with_inter_edge,
    SUM(n_intra_edges)                                        AS total_intra_edges,
    SUM(n_inter_edges)                                        AS total_inter_edges
FROM per_group
GROUP BY pattern_type
ORDER BY (SUM(n_intra_edges) + SUM(n_inter_edges)) DESC;
