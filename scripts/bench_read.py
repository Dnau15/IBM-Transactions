"""Read-side timing for the Stage I format benchmark.

Usage: spark-submit bench_read.py <format> <hdfs_path>
  format    one of {avro, parquet}
  hdfs_path absolute HDFS path holding the imported files

Loads the dataset, forces materialisation via .count(), and prints the
elapsed seconds on the LAST stdout line so the bash driver can tail it.

NOTE: cluster Spark ships with Python 3.6 — do not use 3.7+ syntax
(e.g. `from __future__ import annotations`, `X | Y` unions, walrus, etc.).
"""

import sys
import time

from pyspark.sql import SparkSession


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: bench_read.py <format> <hdfs_path>", file=sys.stderr)
        return 1

    fmt, path = sys.argv[1], sys.argv[2]
    if fmt not in {"avro", "parquet"}:
        print(f"Unsupported format: {fmt}", file=sys.stderr)
        return 1

    spark = (SparkSession.builder
             .appName(f"bench_read_{fmt}")
             .getOrCreate())

    try:
        t0 = time.time()
        df = spark.read.format(fmt).load(path)
        n = df.count()
        elapsed = time.time() - t0
        print(f"[bench_read] format={fmt} path={path} rows={n} "
              f"elapsed={elapsed:.3f}s", file=sys.stderr)
        # Last stdout line is the bare number consumed by the bash driver.
        print(f"{elapsed:.3f}")
    finally:
        spark.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
