"""One-shot CSV -> Parquet load for the AMLworld accounts dimension.

Reads `data/accounts.csv` (header row inferred), normalises the column
names to lower_snake, writes snappy-compressed Parquet to
`/user/team1/project/warehouse/accounts/` on HDFS. Idempotent: the
target directory is wiped on each run.
"""
import re
import sys

from pyspark.sql import SparkSession


# Both paths are on HDFS — Spark runs on YARN, so the executors must
# read the CSV from a distributed filesystem they can all see. The CSV
# is staged to /user/team1/data/ by stage2.sh before this script runs.
HDFS_CSV = "/user/team1/data/accounts.csv"
HDFS_PATH = "/user/team1/project/warehouse/accounts"


def normalise(col: str) -> str:
    """Header -> lower_snake_case identifier."""
    s = col.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def main():
    spark = (SparkSession.builder
             .appName("load_accounts")
             .config("spark.sql.parquet.compression.codec", "snappy")
             .getOrCreate())

    df = (spark.read
          .option("header", True)
          .option("inferSchema", True)
          .csv(HDFS_CSV))

    renamed = df.toDF(*[normalise(c) for c in df.columns])
    print(f"[load_accounts] columns: {renamed.columns}")
    print(f"[load_accounts] rows: {renamed.count()}")

    (renamed.write
     .mode("overwrite")
     .option("compression", "snappy")
     .parquet(HDFS_PATH))

    print(f"[load_accounts] wrote {HDFS_PATH}")
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
