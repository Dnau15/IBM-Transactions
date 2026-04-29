ALTER DATABASE team1_projectdb SET datestyle TO 'ISO, YMD';

START TRANSACTION;

DROP TABLE IF EXISTS laundering_patterns CASCADE;
DROP TABLE IF EXISTS transactions        CASCADE;

CREATE TABLE transactions (
    txn_id              BIGSERIAL PRIMARY KEY,
    timestamp           TIMESTAMP    NOT NULL,
    from_bank           INTEGER      NOT NULL,
    from_account        VARCHAR(50)  NOT NULL,
    to_bank             INTEGER      NOT NULL,
    to_account          VARCHAR(50)  NOT NULL,
    amount_received     NUMERIC(20,4) NOT NULL,
    receiving_currency  VARCHAR(40)  NOT NULL,
    amount_paid         NUMERIC(20,4) NOT NULL,
    payment_currency    VARCHAR(40)  NOT NULL,
    payment_format      VARCHAR(40)  NOT NULL,
    is_laundering       SMALLINT     NOT NULL CHECK (is_laundering IN (0, 1))
);

CREATE TABLE laundering_patterns (
    pattern_id          BIGSERIAL PRIMARY KEY,
    pattern_group       INTEGER      NOT NULL,
    pattern_type        VARCHAR(40)  NOT NULL,
    timestamp           TIMESTAMP    NOT NULL,
    from_bank           INTEGER      NOT NULL,
    from_account        VARCHAR(50)  NOT NULL,
    to_bank             INTEGER      NOT NULL,
    to_account          VARCHAR(50)  NOT NULL,
    amount_received     NUMERIC(20,4) NOT NULL,
    receiving_currency  VARCHAR(40)  NOT NULL,
    amount_paid         NUMERIC(20,4) NOT NULL,
    payment_currency    VARCHAR(40)  NOT NULL,
    payment_format      VARCHAR(40)  NOT NULL,
    is_laundering       SMALLINT     NOT NULL CHECK (is_laundering IN (0, 1))
);

COMMIT;