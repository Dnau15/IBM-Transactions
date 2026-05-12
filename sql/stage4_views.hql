-- Stage IV — register external Hive tables over Stage III output CSVs so
-- Apache Superset can chart them directly via the Hive datasource.
--
-- All inputs are coalesce(1) CSVs written by Spark with
-- .option("header","true"), so every table here uses
-- TBLPROPERTIES ('skip.header.line.count'='1').
--
-- evaluate_models.py already registers team1_projectdb.evaluation; we do
-- NOT redeclare it here. Everything else below is new in Stage IV.

USE team1_projectdb;

-- ----------------------------------------------------------------------
-- A. Model predictions (label, prediction) — one table per model.
--    train_models.py writes coalesce(1) CSV under project/output/modelN_predictions.
-- ----------------------------------------------------------------------

DROP TABLE IF EXISTS model1_predictions;
CREATE EXTERNAL TABLE model1_predictions (
    label      INT,
    prediction INT
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/model1_predictions'
TBLPROPERTIES ('skip.header.line.count'='1');

DROP TABLE IF EXISTS model2_predictions;
CREATE EXTERNAL TABLE model2_predictions (
    label      INT,
    prediction INT
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/model2_predictions'
TBLPROPERTIES ('skip.header.line.count'='1');

-- ----------------------------------------------------------------------
-- B. Rule baseline operating point (single row).
--    rule_baseline.py writes the headline row to project/output/rule_baseline.
--    The headline `evaluation` table (registered by evaluate_models.py) already
--    contains this row; we expose the standalone file separately so the
--    dashboard can compare the per-rule breakdown against the aggregate
--    once the per-rule export is added (currently rule_baseline.py logs
--    each rule's metrics but only writes the aggregate).
-- ----------------------------------------------------------------------

DROP TABLE IF EXISTS rule_baseline_dataset;
CREATE EXTERNAL TABLE rule_baseline_dataset (
    model        STRING,
    precision    DOUBLE,
    recall       DOUBLE,
    f1           DOUBLE,
    pr_auc       DOUBLE,
    alert_volume BIGINT
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/rule_baseline'
TBLPROPERTIES ('skip.header.line.count'='1');

-- ----------------------------------------------------------------------
-- C. Feature extraction pipeline summary (one row per pipeline stage).
--    stage4_prepare.py writes this from the saved PipelineModel.
-- ----------------------------------------------------------------------

DROP TABLE IF EXISTS feature_extraction_summary;
CREATE EXTERNAL TABLE feature_extraction_summary (
    stage_type    STRING,
    input_col     STRING,
    output_col    STRING,
    n_categories  INT,
    top_label     STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/dashboard/feature_extraction'
TBLPROPERTIES ('skip.header.line.count'='1');

-- ----------------------------------------------------------------------
-- D. Best hyperparameters per model (long-form: one row per param).
--    stage4_prepare.py writes this by introspecting the loaded models.
-- ----------------------------------------------------------------------

DROP TABLE IF EXISTS hyperparam_summary;
CREATE EXTERNAL TABLE hyperparam_summary (
    model       STRING,
    param_name  STRING,
    param_value STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/dashboard/hyperparam'
TBLPROPERTIES ('skip.header.line.count'='1');

-- ----------------------------------------------------------------------
-- E. Per-combo CV grid sweep, one table per model.
--    train_models.py writes these as coalesce(1) CSVs at:
--        project/output/cv_results_model1/
--        project/output/cv_results_model2/
--    Long form (model, combo_id, param_name, param_value, pr_auc) — pivot
--    in Superset to chart e.g. PR-AUC vs regParam.
-- ----------------------------------------------------------------------

DROP TABLE IF EXISTS cv_results_model1;
CREATE EXTERNAL TABLE cv_results_model1 (
    model       STRING,
    combo_id    INT,
    param_name  STRING,
    param_value STRING,
    pr_auc      DOUBLE
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/cv_results_model1'
TBLPROPERTIES ('skip.header.line.count'='1');

DROP TABLE IF EXISTS cv_results_model2;
CREATE EXTERNAL TABLE cv_results_model2 (
    model       STRING,
    combo_id    INT,
    param_name  STRING,
    param_value STRING,
    pr_auc      DOUBLE
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/cv_results_model2'
TBLPROPERTIES ('skip.header.line.count'='1');

-- ----------------------------------------------------------------------
-- F. GBT feature importances (one row per feature index).
--    The dashboard joins this against the assembler input-column list
--    (declared in scripts/build_features.py NUMERIC_FEATURES + OHE blocks)
--    to label the top-K features.
-- ----------------------------------------------------------------------

DROP TABLE IF EXISTS feature_importance;
CREATE EXTERNAL TABLE feature_importance (
    feature_index  INT,
    importance     DOUBLE
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'project/output/dashboard/feature_importance'
TBLPROPERTIES ('skip.header.line.count'='1');

-- ----------------------------------------------------------------------
-- G. Sanity checks — every table at a glance. The dashboard SQL editor
--    can use any of these as a starting query.
-- ----------------------------------------------------------------------

SELECT 'evaluation' AS dataset, COUNT(*) AS rows FROM evaluation
UNION ALL SELECT 'rule_baseline_dataset',       COUNT(*) FROM rule_baseline_dataset
UNION ALL SELECT 'feature_extraction_summary',  COUNT(*) FROM feature_extraction_summary
UNION ALL SELECT 'hyperparam_summary',          COUNT(*) FROM hyperparam_summary
UNION ALL SELECT 'cv_results_model1',           COUNT(*) FROM cv_results_model1
UNION ALL SELECT 'cv_results_model2',           COUNT(*) FROM cv_results_model2
UNION ALL SELECT 'feature_importance',          COUNT(*) FROM feature_importance
UNION ALL SELECT 'model1_predictions',          COUNT(*) FROM model1_predictions
UNION ALL SELECT 'model2_predictions',          COUNT(*) FROM model2_predictions;

-- Confusion matrices per model.
SELECT 'model1' AS model, label, prediction, COUNT(*) AS n
FROM model1_predictions
GROUP BY label, prediction;

SELECT 'model2' AS model, label, prediction, COUNT(*) AS n
FROM model2_predictions
GROUP BY label, prediction;

-- Top-10 GBT features by importance.
SELECT feature_index, importance
FROM feature_importance
ORDER BY importance DESC
LIMIT 10;
