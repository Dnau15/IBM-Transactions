# IBM-Transactions

You have to run the scripts from the root directory of the local repository and this is how the TA will test your project. So, make sure that you have configured the scripts according to this rule.

## Stage IV — Apache Superset Dashboard

The dashboard is built manually in Apache Superset on the cluster (per
the rubric: *"Write scripts to automate the tasks above except the
tasks in Apache Superset"*). Two `.hql` files in `sql/` materialize
the supporting Hive objects the dashboard consumes:

```bash
beeline -u jdbc:hive2://hadoop-03.uni.innopolis.ru:10001 \
        -n team1 -w secrets/.psql.pass \
        -f sql/db_stats.hql

beeline -u jdbc:hive2://hadoop-03.uni.innopolis.ru:10001 \
        -n team1 -w secrets/.psql.pass \
        -f sql/stage3_skeleton.hql
```

`db_stats.hql` creates Tab 1 views (per-table record counts, column
datatypes, data samples) plus the `b8_fines` static table.
`stage3_skeleton.hql` creates the `model_hyperparams` reference table
and external tables over the per-model prediction CSVs that
`scripts/stage3.sh` writes.

The exported dashboard zip lives in `superset_export/` once the
dashboard is built and exported from the Superset UI.
