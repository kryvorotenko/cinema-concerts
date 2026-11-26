"""C01 batch report (O4.2), submitted by the DPC API through spark-runner."""

import argparse
import os

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType, StringType, TimestampType


def session() -> SparkSession:
    return (
        SparkSession.builder.appName("c01-lab4-report")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.adaptive.enabled", os.environ.get("SPARK_AQE", "on") == "on")
        .config("spark.sql.adaptive.skewJoin.enabled", os.environ.get("SPARK_AQE", "on") == "on")
        .config("spark.sql.autoBroadcastJoinThreshold", os.environ.get("BROADCAST_THRESHOLD", "10m"))
        .getOrCreate()
    )


def build(facts: DataFrame, dim: DataFrame) -> DataFrame:
    string = StringType()
    scan_types = {"performance_id": string, "gate": string, "accepted": BooleanType(), "event_time": TimestampType()}
    performance_types = dict.fromkeys(("performance_id", "title", "venue", "headliner"), string)
    required = {
        "scans": (facts, scan_types),
        "performances": (dim, performance_types),
    }
    for name, (frame, fields) in required.items():
        for field, dtype in fields.items():
            if field not in frame.columns or frame.schema[field].dataType != dtype:
                raise ValueError(f"{name}.{field} must have type {dtype.simpleString()}")

    performances = dim.select("performance_id", "title", "venue", "headliner")
    invalid_keys = performances.groupBy("performance_id").count().where(
        (F.col("count") != 1) | F.col("performance_id").isNull() | (F.trim("performance_id") == "")
    )
    if invalid_keys.limit(1).count():
        raise ValueError("The performance directory must have unique, nonblank performance_id values")


    salt_count = 8

    accepted = facts.where(F.col("accepted")).select(
        "performance_id",
        "gate",
        "event_time",
        F.pmod(F.xxhash64("scan_id"), F.lit(salt_count)).alias("_salt"),
    )

    directory = (
        performances
        .withColumn("_found", F.lit(True))
        .withColumn(
            "_salt",
            F.explode(F.sequence(F.lit(0), F.lit(salt_count - 1))),
        )
    )

    joined = accepted.join(
        directory, ["performance_id", "_salt"], "left"
    ).drop("_salt")

    invalid_scans = joined.where(
        F.col("_found").isNull() | F.col("gate").isNull() | (F.trim("gate") == "") | F.col("event_time").isNull()
    )
    if invalid_scans.limit(1).count():
        raise ValueError("An accepted scan has an unknown performance_id, missing gate or missing event_time")

    group = Window.partitionBy("performance_id", "gate")
    ranked = joined.withColumn("pass_count", F.count("*").over(group)).withColumn(
        "_position", F.row_number().over(group.orderBy("event_time"))
    )

    middle = ranked.where(F.abs(2 * F.col("_position").cast("long") - F.col("pass_count") - 1) <= 1)
    report = middle.groupBy("performance_id", "gate", "title", "venue", "headliner", "pass_count").agg(
        F.floor(F.avg(F.unix_micros("event_time").cast("decimal(20,0)"))).cast("long").alias("_median_micros")
    )
    return report.withColumn(
        "median_event_time_utc", F.date_format(F.timestamp_micros("_median_micros"), "yyyy-MM-dd'T'HH:mm:ss.SSSSSS'Z'")
    ).drop("_median_micros")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", required=True)
    parser.add_argument("--dim", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--partitions", type=int, default=0)
    args = parser.parse_args()

    spark = session()
    try:
        if args.partitions:
            spark.conf.set("spark.sql.shuffle.partitions", args.partitions)

        report = build(spark.read.parquet(args.facts), spark.read.parquet(args.dim))
        report.write.mode("error").option("ignoreNullFields", "false").json(args.out)
        print(f"report written to {args.out}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
