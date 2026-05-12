-- Stage IV — supporting Hive views for Tab 3 (ML Modeling Results) of
-- the Apache Superset dashboard.
--
-- The Stage III pipeline (scripts/evaluate_models.py) already creates:
--   * team1_projectdb.evaluation               external CSV, headline metrics
--   * team1_projectdb.eval_threshold_sweep     external CSV, operating curve
--
-- This file fills the remaining Tab-3 pieces the rubric calls for:
--   * model_hyperparams         — small reference table for the
--                                 "Hyperparameters" section
--   * model1_predictions /
--     model2_predictions        — external tables over the per-model
--                                 prediction CSVs that stage3.sh pulls
--                                 from HDFS into output/
--
-- Run with:
--
--   beeline -u jdbc:hive2://hadoop-03.uni.innopolis.ru:10001 \
--           -n team1 -w secrets/.psql.pass \
--           -f sql/stage3_skeleton.hql
--
-- Idempotent. Re-run after each Stage III training run to refresh
-- numbers; predictions external tables auto-pick up new CSVs.

USE team1_projectdb;

-- ---------------------------------------------------------------------------
-- 1. Hyperparameters reference table. Two rows per model (the 2 grid
--    params the Stage III rubric requires). Values are PLACEHOLDERS until
--    the team validates the actual best-fit params from
--    train_models.py's bestModel.extractParamMap() output.
--
--    To refresh values: copy the (model, parameter, value) rows from the
--    end-of-run log in scripts/train_models.py and INSERT them here, or
--    extend train_models.py to materialize this table directly.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS model_hyperparams;
CREATE TABLE model_hyperparams (
    model       STRING,
    parameter1  STRING,
    value1      STRING,
    parameter2  STRING,
    value2      STRING
)
STORED AS PARQUET;

INSERT INTO model_hyperparams VALUES
    ('model1_LogisticRegression', 'regParam',        'TBD',
                                   'elasticNetParam', 'TBD'),
    ('model2_GBTClassifier',      'maxDepth',         'TBD',
                                   'maxIter',          'TBD');

-- ---------------------------------------------------------------------------
-- 2. Per-model prediction external tables. stage3.sh's pull step writes
--    output/model{1,2}_predictions.csv locally; the same CSVs sit on HDFS
--    at /user/team1/project/output/model{1,2}_predictions/. We point Hive
--    external tables at the HDFS dirs so Superset can chart them.
--
--    Schema per the Stage III rubric: (label, prediction).
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS model1_predictions;
CREATE EXTERNAL TABLE model1_predictions (
    label       INT,
    prediction  DOUBLE
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
LOCATION '/user/team1/project/output/model1_predictions'
TBLPROPERTIES ('skip.header.line.count'='1');

DROP TABLE IF EXISTS model2_predictions;
CREATE EXTERNAL TABLE model2_predictions (
    label       INT,
    prediction  DOUBLE
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
LOCATION '/user/team1/project/output/model2_predictions'
TBLPROPERTIES ('skip.header.line.count'='1');
