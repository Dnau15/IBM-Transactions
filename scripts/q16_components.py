"""q16 — Weakly-connected-component size distribution via GraphFrames.

Builds an undirected graph from the active-window transactions table
(vertices = accounts, edges = transactions), runs connectedComponents to
label each account with its component id, then aggregates component sizes
into log-binned buckets and writes output/q16.csv.

Why GraphFrames rather than pure Spark SQL? Connected-components on a 32M
edge graph is the cheapest non-trivial graph algorithm; doing it by SQL
self-join would be quadratic. GraphFrames materialises the underlying
algorithm as a Pregel-style iterative join — heavy but bounded.

Run on the cluster via:
    spark-submit \\
        --packages graphframes:graphframes:0.8.2-spark3.2-s_2.12 \\
        --py-files scripts/spark_session.py \\
        scripts/q16_components.py

The graphframes JAR is fetched from Maven; the team1 cluster has internet
access during spark-submit, matching the pattern used elsewhere for the
spark-xgboost JAR. Component-id checkpointing is enabled to keep the
iterative algorithm robust under YARN preemption.
"""
import logging
import os
import sys
import time

from pyspark.sql import functions as F
from spark_session import HIVE_DB, build_session


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [q16] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("q16")

OUT_CSV_DIR = "project/output/q16"   # HDFS path; getmerge'd into output/q16.csv
LOCAL_CSV = "output/q16.csv"


def build_graph(spark):
    """Construct a GraphFrame from transactions.

    Vertices: distinct accounts that appear in either column.
    Edges:    one row per transaction, src = from_account, dst = to_account.

    Note: GraphFrames' connectedComponents treats edges as undirected
    regardless of (src, dst) ordering, which is what we want for weakly
    connected components.
    """
    from graphframes import GraphFrame  # local import — only present at run time

    txn = spark.table(f"{HIVE_DB}.transactions")
    log.info("transactions row count = %s", f"{txn.count():,}")

    vertices = (
        txn.select(F.col("from_account").alias("id"))
            .union(txn.select(F.col("to_account").alias("id")))
            .distinct()
    )
    edges = txn.select(
        F.col("from_account").alias("src"),
        F.col("to_account").alias("dst"),
    )
    log.info("distinct vertices = %s", f"{vertices.count():,}")
    log.info("edges             = %s", f"{edges.count():,}")
    return GraphFrame(vertices, edges)


def main():
    t_start = time.time()
    spark = build_session("q16_components")
    # connectedComponents requires a checkpoint dir on HDFS.
    spark.sparkContext.setCheckpointDir("project/spark-checkpoints/q16")
    log.info("SparkSession ready; checkpoint dir set")

    g = build_graph(spark)

    log.info("running connectedComponents")
    cc = g.connectedComponents()
    component_sizes = (
        cc.groupBy("component")
          .agg(F.count(F.lit(1)).alias("size"))
    )
    n_components = component_sizes.count()
    log.info("found %s components", f"{n_components:,}")

    # Log-binned histogram of component sizes. Bin edges match q11's
    # log10 decades; the giant component goes into the highest bin.
    binned = (
        component_sizes
        .withColumn(
            "size_bucket",
            F.when(F.col("size") == 1,        F.lit("1"))
             .when(F.col("size") == 2,        F.lit("2"))
             .when(F.col("size") < 10,        F.lit("3-9"))
             .when(F.col("size") < 100,       F.lit("10-99"))
             .when(F.col("size") < 1000,      F.lit("100-999"))
             .when(F.col("size") < 10000,     F.lit("1K-9.9K"))
             .when(F.col("size") < 100000,    F.lit("10K-99.9K"))
             .when(F.col("size") < 1000000,   F.lit("100K-999K"))
             .otherwise(F.lit("1M+"))
        )
        .groupBy("size_bucket")
        .agg(F.count(F.lit(1)).alias("n_components"),
             F.sum("size").alias("n_vertices_in_bucket"),
             F.max("size").alias("max_size_in_bucket"))
        .orderBy("size_bucket")
    )

    # Write a single-file CSV; run_eda.sh's getmerge convention does
    # not apply here because we're not going through beeline.
    (binned.coalesce(1)
        .write
        .mode("overwrite")
        .option("header", "true")
        .csv(OUT_CSV_DIR))
    log.info("HDFS CSV part-file written under %s", OUT_CSV_DIR)

    # Driver-side download. Wraps `hdfs dfs -getmerge` because the CSV
    # writer emits a part-NNNN-*.csv plus _SUCCESS marker; getmerge
    # concatenates body and trims spurious files.
    os.makedirs("output", exist_ok=True)
    import subprocess
    subprocess.run(
        ["hdfs", "dfs", "-getmerge", OUT_CSV_DIR, LOCAL_CSV],
        check=True,
    )
    log.info("local CSV at %s", LOCAL_CSV)
    log.info("q16 finished in %.1fs", time.time() - t_start)

    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
