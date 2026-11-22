"""Independent C01 Parquet reference. Run with Python and PyArrow."""

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path


def build_reference(scans: Iterable[dict], performances: Iterable[dict]) -> list[dict]:
    directory = {}
    for performance in performances:
        key = performance["performance_id"]
        if not key or not key.strip() or key in directory:
            raise ValueError("The performance directory must have unique, nonblank performance_id values")
        directory[key] = {field: performance[field] for field in ("title", "venue", "headliner")}

    groups: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for scan in scans:
        if scan["accepted"] is not True:
            continue
        key, gate, arrival = scan["performance_id"], scan["gate"], scan["event_time"]
        if key not in directory or not gate or not gate.strip() or arrival is None or arrival.utcoffset() is None:
            raise ValueError("An accepted scan has an unknown performance_id, missing gate or invalid event_time")
        groups[key, gate].append(arrival.astimezone(UTC))

    rows = []
    for (key, gate), arrivals in sorted(groups.items()):
        arrivals.sort()
        count = len(arrivals)
        earlier, later = arrivals[(count - 1) // 2], arrivals[count // 2]
        median = earlier + (later - earlier) // 2
        rows.append({
            "performance_id": key,
            "gate": gate,
            **directory[key],
            "pass_count": count,
            "median_event_time_utc": median.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        })
    return rows


def read_reference(data_dir: Path) -> list[dict]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    scans = pq.ParquetDataset(data_dir / "scans")
    performances = pq.ParquetDataset(data_dir / "performances")
    for name, dataset, fields in (
        ("scans", scans, {"performance_id": pa.string(), "gate": pa.string(), "accepted": pa.bool_()}),
        ("performances", performances, dict.fromkeys(("performance_id", "title", "venue", "headliner"), pa.string())),
    ):
        for field, dtype in fields.items():
            if field not in dataset.schema.names or dataset.schema.field(field).type != dtype:
                raise ValueError(f"{name}.{field} must have type {dtype}")
    if "event_time" not in scans.schema.names:
        raise ValueError("scans.event_time is required")
    time_type = scans.schema.field("event_time").type
    if not pa.types.is_timestamp(time_type) or time_type.tz is None or time_type.unit == "ns":
        raise ValueError("scans.event_time must be a timestamp with a timezone and at most microsecond precision")
    history = scans.read(columns=["performance_id", "gate", "event_time", "accepted"])
    # Arrow stores zoned timestamps as epoch offsets. Convert directly so UTC
    # decoding also works on Windows without a separate time zone database.
    position = history.schema.get_field_index("event_time")
    micros = history["event_time"].cast(pa.timestamp("us", tz="UTC")).cast(pa.int64())
    history = history.set_column(position, "event_time", micros)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    scan_rows = history.to_pylist()
    for scan in scan_rows:
        if scan["event_time"] is not None:
            scan["event_time"] = epoch + timedelta(microseconds=scan["event_time"])
    return build_reference(
        scan_rows,
        performances.read(columns=["performance_id", "title", "venue", "headliner"]).to_pylist(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, help="Directory containing scans and performances")
    parser.add_argument("--out", type=Path, help="Write a new reference file instead of printing JSON")
    args = parser.parse_args()
    rows = read_reference(args.data_dir)
    result = json.dumps({"rows": rows}, ensure_ascii=True)
    if args.out is None:
        print(result)
    else:
        with args.out.open("x", encoding="utf-8") as output:
            output.write(result + "\n")


if __name__ == "__main__":
    main()
