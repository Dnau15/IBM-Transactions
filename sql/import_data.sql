COPY transactions (
    timestamp, 
    from_bank, 
    from_account, 
    to_bank, 
    to_account, 
    amount_received, 
    receiving_currency, 
    amount_paid, 
    payment_currency, 
    payment_format, 
    is_laundering
) 
FROM STDIN 
WITH CSV HEADER 
DELIMITER ',' 
NULL AS '';

COPY laundering_patterns (
    pattern_group, 
    pattern_type, 
    timestamp, 
    from_bank, 
    from_account, 
    to_bank, 
    to_account, 
    amount_received, 
    receiving_currency, 
    amount_paid, 
    payment_currency, 
    payment_format, 
    is_laundering
) 
FROM STDIN 
WITH CSV HEADER 
DELIMITER ',' 
NULL AS '';
