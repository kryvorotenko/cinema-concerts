"""Refresh the C01 report through the DPC API and compare it with its independent reference."""

import argparse
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def compare_rows(actual: list[dict], reference: list[dict]) -> None:
    def by_key(rows: list[dict]) -> dict:
        indexed = {}
        for row in rows:
            key = (row["performance_id"], row["gate"])
            if key in indexed:
                raise ValueError(f"Duplicate group {key}")
            if type(row["pass_count"]) is not int or not isinstance(row["median_event_time_utc"], str):
                raise ValueError(f"Invalid count or median type for {key}")
            indexed[key] = row
        return indexed

    observed, expected = by_key(actual), by_key(reference)
    if observed.keys() != expected.keys():
        missing, extra = expected.keys() - observed.keys(), observed.keys() - expected.keys()
        raise ValueError(f"Group mismatch: missing {missing}, extra {extra}")
    for key, row in observed.items():
        if row != expected[key]:
            raise ValueError(f"Group {key}: Spark {row}, reference {expected[key]}")


def request(base: str, token: str, method: str, suffix: str = "", expected_status: int = 200) -> dict:
    query = Request(
        f"{base.rstrip('/')}/v1/reports/main{suffix}",
        method=method,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(query, timeout=10) as response:
        if response.status != expected_status:
            raise ValueError(f"Expected HTTP {expected_status}, got {response.status}")
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--timeout", type=int, default=180, help="Seconds to wait for Spark")
    parser.add_argument("--expected-total", type=int, help="Expected number of accepted scans across all groups")
    args = parser.parse_args()
    token = os.environ.get("API_TOKEN", "dev-token")
    try:
        reference = request(args.api, token, "GET", "/reference")["rows"]
        run = request(args.api, token, "POST", "/refresh", expected_status=202)["run"]
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            report = request(args.api, token, "GET")
            if report["run"] != run:
                raise ValueError("The current report changed while the test was polling")
            if report["state"] == "failed":
                raise ValueError(f"Spark report {run} failed. See spark-runner logs and Spark History.")
            if report["state"] == "done":
                rows = report["result"]["rows"]
                compare_rows(rows, reference)
                total = sum(row["pass_count"] for row in rows)
                if args.expected_total is not None and total != args.expected_total:
                    raise ValueError(f"Expected {args.expected_total} accepted scans, got {total}")
                print(f"DPC Lab 4: OK ({len(rows)} groups, {total} accepted scans, run {run})")
                return
            time.sleep(1)
        raise ValueError(f"Spark report {run} did not finish within {args.timeout}s")
    except HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
    except (URLError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
