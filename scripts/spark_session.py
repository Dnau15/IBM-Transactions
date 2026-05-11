"""Shared SparkSession factory for Stage III jobs.

All ML jobs run on YARN against the cluster's Hive metastore (thrift to
hadoop-02). We standardise the AVRO codec to snappy to match the
project/warehouse layout written in Stage I, and set the warehouse dir
to project/hive/warehouse to match Stage II's CREATE DATABASE LOCATION.

Each spark-submit launches its own session — there is no global Python
import path on the cluster, so this module is staged via --py-files
from stage3.sh.
"""
from pyspark.sql import SparkSession


TEAM = "team1"
HIVE_METASTORE_URI = "thrift://hadoop-02.uni.innopolis.ru:9883"
HIVE_WAREHOUSE_DIR = "project/hive/warehouse"
HIVE_DB = f"{TEAM}_projectdb"


def build_session(app_name: str) -> SparkSession:
    """Return a YARN SparkSession with Hive support enabled.

    The `appName` is prefixed with the team identifier so YARN's
    Resource Manager UI groups our apps together. enableHiveSupport()
    + the metastore URI gives access to team1_projectdb.* tables.
    """
    return (
        SparkSession.builder
        .appName(f"{TEAM} - {app_name}")
        .master("yarn")
        .config("hive.metastore.uris", HIVE_METASTORE_URI)
        .config("spark.sql.warehouse.dir", HIVE_WAREHOUSE_DIR)
        .config("spark.sql.avro.compression.codec", "snappy")
        # Match Hive's session config for the BIGINT→TIMESTAMP +3h MSK shift
        # already applied in sql/db.hql — Spark reads the cast TIMESTAMP column.
        .config("spark.sql.session.timeZone", "Europe/Moscow")
        # Keep the executor count modest; HI-Medium transactions are ~31M rows.
        # Larger configs risk YARN preemption when other teams run jobs.
        .config("spark.executor.memory", "4g")
        .config("spark.driver.memory", "2g")
        .enableHiveSupport()
        .getOrCreate()
    )
