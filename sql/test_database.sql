SELECT 'transactions row count' AS check_name, 
       COUNT(*) AS value 
FROM transactions;

SELECT 'laundering_patterns row count' AS check_name, 
       COUNT(*) AS value 
FROM laundering_patterns;

SELECT 'transactions laundering ratio' AS check_name, 
       ROUND(100.0 * SUM(is_laundering)::numeric / COUNT(*), 4) AS value 
FROM transactions;

SELECT 'distinct payment_format values' AS check_name, 
       COUNT(DISTINCT payment_format) AS value 
FROM transactions;

SELECT 'distinct pattern_type values' AS check_name, 
       COUNT(DISTINCT pattern_type) AS value 
FROM laundering_patterns;

SELECT 'min timestamp' AS check_name, 
       MIN(timestamp)::text AS value 
FROM transactions;

SELECT 'max timestamp' AS check_name, 
       MAX(timestamp)::text AS value 
FROM transactions;

SELECT * 
FROM transactions 
ORDER BY txn_id 
LIMIT 5;

SELECT * 
FROM laundering_patterns 
ORDER BY pattern_id 
LIMIT 5;
