"""Stage III — Tier 1 vertex-statistics feature engineering + temporal 80/20 split.

Reads team1_projectdb.transactions, adds past-only window aggregates per
account (in/out, multiple time horizons), one-hot encodes payment_format
and currency buckets, then temporally splits the result 80/20 by ts.

Outputs (HDFS, paths relative to /user/team1):
    project/data/features              full feature table, Parquet+Snappy
    project/data/train                 train split, JSON  ({features, label, ts})
    project/data/test                  test  split, JSON  ({features, label, ts})
    project/data/feature_pipeline      fitted PipelineModel (StringIndexer +
                                       OneHotEncoder + VectorAssembler)

Hive side-effect:
    team1_projectdb.features           external Parquet over project/data/features
                                       (consumed by scripts/rule_baseline.py)

Temporal discipline (see ml.md §2):
    - Window aggregates use RANGE BETWEEN N PRECEDING AND CURRENT ROW —
      cannot see rows with a higher ts_unix, so no future leakage.
    - The encoding pipeline (StringIndexer/OHE) is fit on the TRAIN
      split only, then applied to test. Any category present in test
      but absent in train is routed to the "keep" sentinel index, not
      retro-fit-leaked.
"""
import logging
import os
import sys
import time
from contextlib import contextmanager

from pyspark.ml import Pipeline
from pyspark.ml.feature import OneHotEncoder, StringIndexer, VectorAssembler
from pyspark.sql import Window
from pyspark.sql import functions as F

from spark_session import HIVE_DB, build_session


# -----------------------------------------------------------------------------
# Dataset-size knobs for iterative development.
#
# Both are optional env vars; default behavior is "process the whole table".
#
#   SAMPLE_FRACTION=0.01    random 1% row sample after the day filter.
#                           Cheapest smoke test, but window features lose
#                           accuracy (counts/sums drop ~100×).
#
#   LIMIT_DAYS=2            keep only the first N days of data via
#                           txn_date partition pruning. Window features
#                           remain accurate within the kept days, so
#                           model metrics on the sample are interpretable.
#
# The two are independent — you can combine them (e.g., LIMIT_DAYS=4
# SAMPLE_FRACTION=0.5 to halve a 4-day window). When either is active
# the script logs a loud WARNING so you don't forget you're on a subset.
# -----------------------------------------------------------------------------

SAMPLE_FRACTION = os.environ.get("SAMPLE_FRACTION")
LIMIT_DAYS = os.environ.get("LIMIT_DAYS")
# The Stage II active-window filter starts here — used to translate
# LIMIT_DAYS into a concrete date predicate without a driver-side action.
DATA_START_DATE = "2022-09-01"
DEV_MODE_SEED = 42


# -----------------------------------------------------------------------------
# Logging — driver-side. Output flows into the spark-submit terminal and
# YARN's stdout for the application driver. We want timestamps because
# Stage III phases can run 5–20 min each on HI-Medium and "did it hang?"
# is otherwise unanswerable from a frozen terminal.
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [build_features] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("build_features")


# Step counter and total — set in main() once we know the phase count.
# Used by step() to print "(N/M)" prefixes so progress is obvious.
TOTAL_STEPS = 10
_step_counter = {"n": 0}


@contextmanager
def step(name: str):
    """Wrap a phase with a banner + elapsed-time footer.

    Usage:
        with step("read transactions"):
            txn = spark.table(...)
            ...
    """
    _step_counter["n"] += 1
    n = _step_counter["n"]
    log.info("=" * 70)
    log.info(">>> step %d/%d: %s", n, TOTAL_STEPS, name)
    log.info("=" * 70)
    t0 = time.time()
    yield
    log.info("<<< step %d/%d: %s  done in %.1fs", n, TOTAL_STEPS, name, time.time() - t0)


# --- Hive tables --------------------------------------------------------------

TRANSACTIONS_TABLE = f"{HIVE_DB}.transactions"
FEATURES_TABLE = f"{HIVE_DB}.features"

# --- HDFS paths (relative to /user/team1) -------------------------------------

HDFS_FEATURES_PARQUET = "project/data/features"
HDFS_TRAIN_JSON = "project/data/train"
HDFS_TEST_JSON = "project/data/test"
# Parquet duplicates of the train/test splits — JSON loses the Vector
# type tag, so downstream scripts (train_models.py, evaluate_models.py)
# read Parquet which preserves it. JSON files exist solely to satisfy
# the Stage III rubric.
HDFS_TRAIN_PARQUET = "project/data/train_parquet"
HDFS_TEST_PARQUET = "project/data/test_parquet"
HDFS_PIPELINE = "project/data/feature_pipeline"

# --- Time-window sizes in seconds --------------------------------------------

ONE_HOUR = 3600
ONE_DAY = 86400

# --- Bank target-encoding smoothing strength ---------------------------------
# K&K formula: prior_i = (n_i * mean_i + α * global_mean) / (n_i + α).
# At α=20, a bank needs ≥20 train transactions before its own laundering
# rate dominates the global mean in the smoothed prior.
BANK_PRIOR_ALPHA = 20

# --- Feature column lists -----------------------------------------------------

# Per-row features (no window, computed from raw transaction).
# Added vs original Stage III:
#   is_weekend            — binary form of day_of_week, q12 shows weekend
#                           midday rate is 2-3× weekday baseline.
#   log10_amount_bucket   — integer bin matching q11 buckets; laundering
#                           is right-shifted vs legit on the amount axis.
ROW_NUMERIC = [
    "log_amount",
    "log10_amount_bucket",
    "currency_mismatch",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
]

# Bank-level target-encoded priors. Joined onto rows AFTER the split is
# made, computed from TRAIN only to avoid label leakage. q8 shows banks
# differ by 30× in laundering rate at >100-tx scale; the prior captures
# this directly. Unseen test banks fall back to the global rate via the
# degenerate case of the K&K formula (n_i = 0 ⇒ prior = global_mean).
BANK_PRIORS = [
    "from_bank_laundering_rate_prior",
    "to_bank_laundering_rate_prior",
]

# Past-24h window features keyed on from_account (outgoing side).
OUT_24H_NUMERIC = [
    "out_count_24h",
    "out_sum_24h",
    "out_mean_24h",
    "out_std_24h",
    "out_max_24h",
    "out_unique_dst_24h",
    "out_unique_banks_24h",
]

# Past-24h window features keyed on to_account (incoming side).
IN_24H_NUMERIC = [
    "in_count_24h",
    "in_sum_24h",
    "in_mean_24h",
    "in_unique_src_24h",
    "in_unique_banks_24h",
]

# Past-1h velocity features keyed on from_account — needed by rule R2.
OUT_1H_NUMERIC = [
    "out_count_1h",
    "out_sum_1h",
]

NUMERIC_FEATURES = (
    ROW_NUMERIC
    + OUT_24H_NUMERIC
    + IN_24H_NUMERIC
    + OUT_1H_NUMERIC
    + BANK_PRIORS         # joined later, but already part of the final vector spec
)

# Extra non-feature columns carried into the Parquet splits for downstream
# diagnostic analyses in evaluate_models.py: per-pattern-group recall
# (needs from_account/to_account/amount_paid for the patterns join),
# weekend/weekday recall breakdown (needs is_weekend), and per-format
# diagnostics. Stripped before the VectorAssembler, so they never bias
# the model — they are just metadata columns.
DIAGNOSTIC_COLS = [
    "txn_id",
    "ts_unix",
    "from_account",
    "to_account",
    "from_bank",
    "to_bank",
    "amount_paid",
    "payment_format",
    "is_weekend",
    "day_of_week",
    "hour_of_day",
]

# Categorical columns one-hot encoded by the pipeline. Currencies are
# bucketed to "top-N + other" before encoding to keep the vector compact.
CATEGORICAL_FEATURES = [
    "payment_format",
    "payment_currency_bucket",
    "receiving_currency_bucket",
]

# Currencies kept distinct after bucketing — every other value collapses
# to "Other". Chosen to cover ~95% of HI-Medium rows by frequency
# (verified empirically via Stage II EDA).
TOP_CURRENCIES = {
    "US Dollar", "Euro", "Yuan", "Yen", "UK Pound",
    "Ruble", "Canadian Dollar", "Australian Dollar",
}

# Train/test cut as a fraction of the timestamp range.
TRAIN_FRACTION = 0.80


# -----------------------------------------------------------------------------
# Feature engineering
# -----------------------------------------------------------------------------

def compute_row_features(df):
    """Add per-row features that don't need a window."""
    return (
        df
        # ln(1 + amount) — compresses the 6-order-of-magnitude tail.
        .withColumn("log_amount", F.log1p(F.col("amount_paid")))
        # q11-aligned log10 bin: 0 for amount≤0, 1 for $0–1, 2 for $1–10,
        # …, 10 for $100M+. Clipped on the upper end so the encoder sees
        # a bounded categorical-like integer.
        .withColumn(
            "log10_amount_bucket",
            F.when(F.col("amount_paid") <= 0, F.lit(0))
             .otherwise(
                 F.least(
                     F.lit(10),
                     F.floor(F.log10(F.col("amount_paid"))).cast("int") + F.lit(1),
                 )
             ),
        )
        # 1 if FX is involved on this transaction.
        # q13: 0/31,146 laundering rows are cross-currency in HI-Medium —
        # this is a null signal here. Kept for completeness so feature
        # selection can flag it and the report can document the finding.
        .withColumn(
            "currency_mismatch",
            (F.col("payment_currency") != F.col("receiving_currency")).cast("int"),
        )
        .withColumn("hour_of_day", F.hour("ts"))
        # dayofweek is 1=Sunday..7=Saturday in Spark; that's fine as a numeric.
        .withColumn("day_of_week", F.dayofweek("ts"))
        # Binary form of day_of_week — easier for tree splits than a 7-level
        # categorical. q12 shows weekend midday laundering rate is ~3× the
        # weekday baseline.
        .withColumn(
            "is_weekend",
            F.when(F.dayofweek("ts").isin(1, 7), F.lit(1)).otherwise(F.lit(0)),
        )
        # unix seconds, needed as window ordering key (RANGE windows require
        # a numeric, not a TIMESTAMP).
        .withColumn("ts_unix", F.col("ts").cast("long"))
        # Currency bucketing — collapse rare currencies to "Other".
        .withColumn(
            "payment_currency_bucket",
            F.when(F.col("payment_currency").isin(*TOP_CURRENCIES), F.col("payment_currency"))
             .otherwise(F.lit("Other")),
        )
        .withColumn(
            "receiving_currency_bucket",
            F.when(F.col("receiving_currency").isin(*TOP_CURRENCIES), F.col("receiving_currency"))
             .otherwise(F.lit("Other")),
        )
    )


def add_outgoing_windows(df):
    """Add past-window features keyed on the sender (from_account)."""
    w24 = (
        Window
        .partitionBy("from_account")
        .orderBy("ts_unix")
        .rangeBetween(-ONE_DAY, 0)
    )
    w1 = (
        Window
        .partitionBy("from_account")
        .orderBy("ts_unix")
        .rangeBetween(-ONE_HOUR, 0)
    )
    return (
        df
        # 24h aggregates
        .withColumn("out_count_24h", F.count(F.lit(1)).over(w24))
        .withColumn("out_sum_24h", F.sum("amount_paid").over(w24))
        .withColumn("out_mean_24h", F.avg("amount_paid").over(w24))
        # stddev_samp returns NULL on a single-row window; coalesce to 0.
        .withColumn("out_std_24h", F.coalesce(F.stddev_samp("amount_paid").over(w24), F.lit(0.0)))
        .withColumn("out_max_24h", F.max("amount_paid").over(w24))
        # collect_set is windowable; size() converts to cardinality.
        .withColumn("out_unique_dst_24h", F.size(F.collect_set("to_account").over(w24)))
        .withColumn("out_unique_banks_24h", F.size(F.collect_set("to_bank").over(w24)))
        # 1h velocity
        .withColumn("out_count_1h", F.count(F.lit(1)).over(w1))
        .withColumn("out_sum_1h", F.sum("amount_paid").over(w1))
    )


def add_incoming_windows(df):
    """Add past-window features keyed on the receiver (to_account)."""
    w24 = (
        Window
        .partitionBy("to_account")
        .orderBy("ts_unix")
        .rangeBetween(-ONE_DAY, 0)
    )
    return (
        df
        .withColumn("in_count_24h", F.count(F.lit(1)).over(w24))
        .withColumn("in_sum_24h", F.sum("amount_received").over(w24))
        .withColumn("in_mean_24h", F.avg("amount_received").over(w24))
        .withColumn("in_unique_src_24h", F.size(F.collect_set("from_account").over(w24)))
        .withColumn("in_unique_banks_24h", F.size(F.collect_set("from_bank").over(w24)))
    )


def compute_bank_priors(train_raw, alpha=BANK_PRIOR_ALPHA):
    """K&K-smoothed per-bank laundering rate, computed on TRAIN ONLY.

    Returns (from_priors_df, to_priors_df, global_mean).

    Formula: prior_i = (n_i * mean_i + α * g) / (n_i + α)
    where n_i = #train txns at bank i, mean_i = laundering rate at bank i
    on train, g = global train laundering rate. For an unseen test bank
    (n_i = 0), prior = g — handled at JOIN time by fillna(g).

    Each prior DF has one row per bank (~30 banks in HI-Medium) so the
    downstream join is broadcast.
    """
    g = float(train_raw.agg(F.mean("label")).collect()[0][0] or 0.0)

    def side(bank_col, out_col):
        return (
            train_raw
            .groupBy(bank_col)
            .agg(
                F.count(F.lit(1)).alias("n"),
                F.mean("label").alias("m"),
            )
            .withColumn(
                out_col,
                (F.col("n") * F.col("m") + F.lit(alpha) * F.lit(g))
                / (F.col("n") + F.lit(alpha)),
            )
            .select(bank_col, out_col)
        )

    return (
        side("from_bank", "from_bank_laundering_rate_prior"),
        side("to_bank",   "to_bank_laundering_rate_prior"),
        g,
    )


def join_bank_priors(df, from_priors, to_priors, global_mean):
    """LEFT-join broadcast bank priors; coalesce unseen banks to global mean.

    Using F.broadcast forces a map-side join — no shuffle on the big
    feature table. The fillna at the end handles the unseen-test-bank
    case (n_i = 0 in train).
    """
    df = df.join(F.broadcast(from_priors), on="from_bank", how="left")
    df = df.join(F.broadcast(to_priors),   on="to_bank",   how="left")
    return df.fillna({
        "from_bank_laundering_rate_prior": global_mean,
        "to_bank_laundering_rate_prior":   global_mean,
    })


def build_features(spark):
    """Read transactions, compute all Tier 1 features, return DataFrame.

    This is the public entry point used by the notebook and by main().
    No actions are triggered — the DataFrame returned is fully lazy.
    Bank priors are NOT added here because they require labels and the
    split-cutoff; they're added in main() after the temporal split.
    """
    log.info("reading hive table %s", TRANSACTIONS_TABLE)
    # REFRESH guards against a stale metastore cache from a previous failed
    # run leaving us pointed at an empty/old location for the table.
    spark.sql(f"REFRESH TABLE {TRANSACTIONS_TABLE}")
    txn = spark.table(TRANSACTIONS_TABLE)

    # Pre-filter row count — the only number that distinguishes "underlying
    # read is empty" from "downstream sample/filter killed everything". If
    # this is 0 the bug is upstream (metastore / Stage II); if it's huge but
    # the materialized features Parquet is 0, the bug is in the windowing or
    # the saveAsTable target path.
    pre_filter_rows = txn.count()
    log.info("transactions row count (pre-filter) = %s", f"{pre_filter_rows:,}")
    if pre_filter_rows == 0:
        raise RuntimeError(
            f"{TRANSACTIONS_TABLE} returned 0 rows in this Spark session — "
            "check metastore binding and Stage II load before retrying"
        )

    # Optional dev-mode subsetting. Order matters: LIMIT_DAYS uses
    # partition pruning (essentially free), SAMPLE_FRACTION applies a
    # random sample AFTER the day filter so the sample budget is
    # spent on the surviving days.
    if LIMIT_DAYS:
        n_days = int(LIMIT_DAYS)
        log.warning(
            "DEV MODE: LIMIT_DAYS=%d — keeping only first %d days from %s",
            n_days, n_days, DATA_START_DATE,
        )
        txn = txn.filter(
            F.datediff(F.col("txn_date"), F.lit(DATA_START_DATE)) < n_days
        )

    if SAMPLE_FRACTION:
        frac = float(SAMPLE_FRACTION)
        log.warning(
            "DEV MODE: SAMPLE_FRACTION=%.4f — random row sample (seed=%d)",
            frac, DEV_MODE_SEED,
        )
        txn = txn.sample(
            withReplacement=False,
            fraction=frac,
            seed=DEV_MODE_SEED,
        )

    log.info("adding per-row features (%d cols)", len(ROW_NUMERIC))
    df = compute_row_features(txn)

    log.info("adding outgoing window features (%d cols, windows = 24h + 1h)",
             len(OUT_24H_NUMERIC) + len(OUT_1H_NUMERIC))
    df = add_outgoing_windows(df)

    log.info("adding incoming window features (%d cols, window = 24h)",
             len(IN_24H_NUMERIC))
    df = add_incoming_windows(df)

    # Rename target to 'label' (Spark ML convention).
    df = df.withColumnRenamed("is_laundering", "label")

    return df


# -----------------------------------------------------------------------------
# Encoding pipeline
# -----------------------------------------------------------------------------

def build_pipeline():
    """Construct the StringIndexer + OneHotEncoder + VectorAssembler pipeline.

    `handleInvalid="keep"` on the StringIndexer routes unseen test
    categories to a sentinel index instead of dropping the row — important
    because temporal split can move a rare payment format entirely into
    the test window.
    """
    indexers = [
        StringIndexer(
            inputCol=col,
            outputCol=f"{col}_idx",
            handleInvalid="keep",
        )
        for col in CATEGORICAL_FEATURES
    ]
    encoders = [
        OneHotEncoder(
            inputCol=f"{col}_idx",
            outputCol=f"{col}_ohe",
            dropLast=True,
        )
        for col in CATEGORICAL_FEATURES
    ]
    assembler_inputs = (
        [f"{col}_ohe" for col in CATEGORICAL_FEATURES] + NUMERIC_FEATURES
    )
    assembler = VectorAssembler(
        inputCols=assembler_inputs,
        outputCol="features",
        # If a window aggregate is NULL (lone-row partition), skip the row.
        # Should be rare in practice — most accounts transact more than once.
        handleInvalid="skip",
    )
    return Pipeline(stages=indexers + encoders + [assembler])


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def _log_class_balance(df, name):
    """Print positive / total / rate. df.count() forces materialization."""
    agg = df.agg(
        F.count(F.lit(1)).alias("total"),
        F.sum(F.col("label").cast("long")).alias("pos"),
    ).collect()[0]
    total = int(agg["total"] or 0)
    pos = int(agg["pos"] or 0)
    rate = (pos / total * 100.0) if total else 0.0
    log.info("    %-5s : %s positive / %s total (%.4f%%)",
             name, f"{pos:,}", f"{total:,}", rate)


def main():
    t_start = time.time()
    log.info("starting Stage III feature build, target = %d steps", TOTAL_STEPS)

    spark = build_session("build_features")
    log.info("SparkSession ready  appId=%s  master=%s",
             spark.sparkContext.applicationId, spark.sparkContext.master)

    # -------------------------------------------------------------------------
    # 1. Build the lazy feature DataFrame.
    # -------------------------------------------------------------------------
    with step("compute Tier 1 vertex features (lazy DAG)"):
        df_lazy = build_features(spark)
        log.info("output schema = %d columns  (numeric=%d, categorical=%d, +id/meta)",
                 len(df_lazy.columns), len(NUMERIC_FEATURES), len(CATEGORICAL_FEATURES))
        log.info("input partitions = %d", df_lazy.rdd.getNumPartitions())

    # -------------------------------------------------------------------------
    # 2. Materialize features to Parquet + register Hive table. This forces
    #    the entire window-function DAG to run ONCE; every subsequent step
    #    re-reads from the materialized Parquet at I/O speed instead of
    #    re-shuffling 30M rows for windowing.
    # -------------------------------------------------------------------------
    with step(f"materialize features -> {HDFS_FEATURES_PARQUET} + hive {FEATURES_TABLE}"):
        log.info("dropping previous Hive table (if any)")
        spark.sql(f"DROP TABLE IF EXISTS {FEATURES_TABLE}")
        log.info("running saveAsTable — this triggers the windowed DAG")
        (df_lazy.write
            .mode("overwrite")
            .option("compression", "snappy")
            .option("path", HDFS_FEATURES_PARQUET)
            .format("parquet")
            .saveAsTable(FEATURES_TABLE))
        log.info("write complete; re-reading from disk for downstream steps")
        # Re-read so subsequent operations hit Parquet, not the window DAG.
        df = spark.table(FEATURES_TABLE)
        n_rows = df.count()
        log.info("materialized %s rows across %d output partitions",
                 f"{n_rows:,}", df.rdd.getNumPartitions())

    # -------------------------------------------------------------------------
    # 3. Diagnostics — categorical cardinalities + overall class balance.
    #    Cheap because we're scanning the Parquet, not redoing the windows.
    # -------------------------------------------------------------------------
    with step("diagnose categoricals + global class balance"):
        for col in CATEGORICAL_FEATURES:
            n_distinct = df.select(col).distinct().count()
            log.info("    %-26s : %d distinct values", col, n_distinct)
        _log_class_balance(df, "full")

    # -------------------------------------------------------------------------
    # 4. Compute the 80/20 temporal cutoff via approxQuantile (streaming,
    #    O(n)). 0.001 relative error is more than enough at 30M rows.
    # -------------------------------------------------------------------------
    with step(f"compute temporal cutoff at p{int(TRAIN_FRACTION * 100)}"):
        (cutoff,) = df.approxQuantile("ts_unix", [TRAIN_FRACTION], 0.001)
        cutoff_iso = (
            spark.sql(f"SELECT from_unixtime({int(cutoff)}) AS iso")
            .collect()[0]["iso"]
        )
        log.info("cutoff ts_unix = %d  (%s MSK)", int(cutoff), cutoff_iso)

    # -------------------------------------------------------------------------
    # 5. Split + per-split row counts and class balance.
    # -------------------------------------------------------------------------
    with step("split train/test temporally + report class balance"):
        train_raw = df.filter(F.col("ts_unix") <= cutoff)
        test_raw = df.filter(F.col("ts_unix") > cutoff)
        log.info("per-split class balance:")
        _log_class_balance(train_raw, "train")
        _log_class_balance(test_raw, "test")

    # -------------------------------------------------------------------------
    # 5b. Compute bank-level target-encoded priors on TRAIN ONLY (the only
    #     leakage-safe way to use labels as a feature) and broadcast-join
    #     them onto BOTH splits. K&K smoothing means unseen test banks
    #     gracefully fall back to the global train rate.
    # -------------------------------------------------------------------------
    with step("compute bank target-encoded priors (train only) + join"):
        from_priors, to_priors, global_mean = compute_bank_priors(train_raw)
        log.info("global train laundering rate g = %.6f", global_mean)
        n_from = from_priors.count()
        n_to = to_priors.count()
        log.info("from_bank priors: %d banks  /  to_bank priors: %d banks",
                 n_from, n_to)
        log.info("top-5 riskiest from_banks (post-smoothing):")
        for r in (from_priors
                  .orderBy(F.col("from_bank_laundering_rate_prior").desc())
                  .limit(5).collect()):
            log.info("    from_bank=%s  prior=%.4f",
                     r["from_bank"], r["from_bank_laundering_rate_prior"])

        train_raw = join_bank_priors(train_raw, from_priors, to_priors, global_mean)
        test_raw = join_bank_priors(test_raw, from_priors, to_priors, global_mean)
        log.info("after join: train cols=%d, test cols=%d",
                 len(train_raw.columns), len(test_raw.columns))

    # -------------------------------------------------------------------------
    # 6. Fit the encoding pipeline on TRAIN only, transform both splits.
    #    Carry the DIAGNOSTIC_COLS through so evaluate_models.py can do
    #    per-pattern / weekend-weekday recall breakdowns without rejoining.
    # -------------------------------------------------------------------------
    with step("fit encoding pipeline on train only, transform train+test"):
        pipeline = build_pipeline()
        log.info("pipeline stages = %d  (%d indexers + %d encoders + 1 assembler)",
                 len(pipeline.getStages()), len(CATEGORICAL_FEATURES), len(CATEGORICAL_FEATURES))
        log.info("fitting on train (triggers a scan to learn category indices)")
        pipeline_model = pipeline.fit(train_raw)

        # Log learned category vocabularies so we can sanity-check that
        # the StringIndexer saw what we expected (no surprise NULLs).
        # The first len(CATEGORICAL_FEATURES) stages are the indexers.
        for col, model in zip(CATEGORICAL_FEATURES, pipeline_model.stages[:len(CATEGORICAL_FEATURES)]):
            log.info("    indexer[%s] learned labels = %s",
                     col, list(model.labels))

        keep_cols = ["features", "label"] + DIAGNOSTIC_COLS
        train = pipeline_model.transform(train_raw).select(*keep_cols)
        test = pipeline_model.transform(test_raw).select(*keep_cols)

    # -------------------------------------------------------------------------
    # 7. Write Parquet splits (the ones train_models.py + evaluate_models.py
    #    actually read — Vector type survives Parquet but not JSON).
    # -------------------------------------------------------------------------
    with step("write Parquet splits (for downstream ML scripts)"):
        log.info("writing train -> %s", HDFS_TRAIN_PARQUET)
        (train.write.mode("overwrite")
            .option("compression", "snappy")
            .parquet(HDFS_TRAIN_PARQUET))
        log.info("writing test  -> %s", HDFS_TEST_PARQUET)
        (test.write.mode("overwrite")
            .option("compression", "snappy")
            .parquet(HDFS_TEST_PARQUET))

    # -------------------------------------------------------------------------
    # 8. Write JSON splits (rubric deliverable). We strip diagnostic cols
    #    here — the rubric example shows {features, label} only — and
    #    coalesce(1) so the downstream `hdfs dfs -cat .../part-*.json >
    #    data/train.json` is a single concat. The Vector becomes a struct
    #    in JSON; that's fine for the grader to read, not consumed by our
    #    own training code (which reads Parquet).
    # -------------------------------------------------------------------------
    with step("write JSON splits (rubric deliverable) + pipeline model"):
        log.info("writing train json -> %s", HDFS_TRAIN_JSON)
        (train.select("features", "label").coalesce(1)
            .write.mode("overwrite").format("json").save(HDFS_TRAIN_JSON))
        log.info("writing test  json -> %s", HDFS_TEST_JSON)
        (test.select("features", "label").coalesce(1)
            .write.mode("overwrite").format("json").save(HDFS_TEST_JSON))
        log.info("writing pipeline   -> %s", HDFS_PIPELINE)
        pipeline_model.write().overwrite().save(HDFS_PIPELINE)

    # -------------------------------------------------------------------------
    # 9. Final summary — all outputs + total elapsed time.
    # -------------------------------------------------------------------------
    with step("summary"):
        log.info("HDFS outputs (relative to /user/team1):")
        for label, path in [
            ("features parquet", HDFS_FEATURES_PARQUET),
            ("train parquet   ", HDFS_TRAIN_PARQUET),
            ("test parquet    ", HDFS_TEST_PARQUET),
            ("train json      ", HDFS_TRAIN_JSON),
            ("test json       ", HDFS_TEST_JSON),
            ("pipeline model  ", HDFS_PIPELINE),
        ]:
            log.info("    %s  ->  %s", label, path)
        log.info("Hive table: %s", FEATURES_TABLE)

    log.info("build_features.py finished in %.1fs", time.time() - t_start)
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())