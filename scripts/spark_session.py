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
        # -------------------------------------------------------------------
        # YARN resource budget — must stay under team1's hard cap of
        # 20 GB RAM / 12 vCores (shared cluster, other teams co-tenants).
        #
        #   3 executors × (4 GB heap + 1 GB overhead) = 15 GB executor pool
        #   3 executors × 3 cores                     =  9 executor cores
        #   driver: 2 GB + ~0.4 GB overhead + 1 core  ≈  2.4 GB,  1 core
        #   ────────────────────────────────────────────────────────────
        #   TOTAL ≈ 17.4 GB / 10 cores   (2.6 GB / 2 cores headroom)
        #
        # Each container is 5 GB / 3 cores — well below the cluster's
        # 15 GB / 15-core per-container ceiling.
        #
        # Why fixed allocation, not dynamicAllocation:
        #   - shuffle service isn't enabled cluster-wide for team1, so
        #     dynamicAllocation can't release executors cleanly.
        #   - Fixed allocation is more predictable for CrossValidator's
        #     parallel-fit scheduling (we pin parallelism=3 in train_models).
        # -------------------------------------------------------------------
        .config("spark.executor.memory", "4g")
        .config("spark.executor.memoryOverhead", "1g")
        .config("spark.executor.cores", "3")
        .config("spark.executor.instances", "3")
        .config("spark.driver.memory", "2g")
        .config("spark.driver.cores", "1")
        # Shuffle partitions: ~10× executor cores. The default 200 produces
        # ~3 k rows/partition on the post-downsample train (500 k rows),
        # which is task-overhead bound; 96 = ~5 k rows/partition for train
        # and ~300 k rows/partition for the full features build.
        .config("spark.sql.shuffle.partitions", "96")
        .config("spark.default.parallelism", "96")
        # KryoSerializer cuts shuffle bytes ~2-5× on Python UDF closures
        # and broadcast joins. No-op for Tungsten-encoded columnar shuffles
        # but cheap insurance for the RDD-level paths (rule_baseline metrics,
        # threshold sweep aggregation).
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .enableHiveSupport()
        .getOrCreate()
    )
