"""One-shot CSV -> Parquet load for the AMLworld accounts dimension.

Reads accounts CSV from HDFS (staged by stage2.sh), writes
snappy-compressed Parquet to /user/team1/project/warehouse/accounts/.
Idempotent: target dir overwritten each run.

Schema is explicit (not inferred) so it matches the column types
declared in sql/db.hql for the EXTERNAL accounts table. CSV header is:
    Bank Name, Bank ID, Account Number, Entity ID, Entity Name
"""
import sys

from pyspark.sql import SparkSession
from pyspark.sql.types import LongType, StringType, StructField, StructType


HDFS_CSV = "/user/team1/data/accounts.csv"
HDFS_PATH = "/user/team1/project/warehouse/accounts"

ACCOUNTS_SCHEMA = StructType([
    StructField("bank_name",      StringType(), True),
    StructField("bank_id",        LongType(),   True),
    StructField("account_number", StringType(), True),
    StructField("entity_id",      StringType(), True),
    StructField("entity_name",    StringType(), True),
])


def main():
    spark = (SparkSession.builder
             .appName("load_accounts")
             .config("spark.sql.parquet.compression.codec", "snappy")
             .getOrCreate())

    df = (spark.read
          .option("header", True)
          .schema(ACCOUNTS_SCHEMA)
          .csv(HDFS_CSV))

    print(f"[load_accounts] columns: {df.columns}")
    print(f"[load_accounts] rows: {df.count()}")

    (df.write
     .mode("overwrite")
     .option("compression", "snappy")
     .parquet(HDFS_PATH))

    print(f"[load_accounts] wrote {HDFS_PATH}")
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
