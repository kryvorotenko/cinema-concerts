import time

from pyspark.sql import SparkSession


def count_slowly(partition_index, rows):
    count = sum(1 for _ in rows)
    time.sleep(30)
    yield partition_index, count


def main():
    spark = (
        SparkSession.builder
        .appName("c01-lab4-o45-recovery")
        .getOrCreate()
    )

    spark.sparkContext.setLogLevel("WARN")

    try:
        scans = spark.read.parquet("/data/c01-lab4-large/scans")
        partitions = scans.select("scan_id").repartition(12)

        counts = (
            partitions.rdd
            .mapPartitionsWithIndex(count_slowly)
            .collect()
        )

        total = sum(count for _, count in counts)

        print(
            f"O4.5 RESULT: rows={total}, partitions={len(counts)}",
            flush=True,
        )

        if total != 100000 or len(counts) != 12:
            raise RuntimeError("O4.5 verification failed")

        print("O4.5 DATA CHECK: PASS", flush=True)

    finally:
        spark.stop()


if __name__ == "__main__":
    main()