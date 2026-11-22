"""Lightweight C01 reference and comparison tests without Spark or Docker."""

import unittest
from datetime import UTC, datetime, timedelta, timezone

from dpc.spark.jobs.report_reference import build_reference
from experiments.check_dpc_lab4 import compare_rows

PERFORMANCE = {"performance_id": "p1", "title": "Concert", "venue": "Hall", "headliner": "Band"}
START = datetime(2026, 11, 19, 18, tzinfo=UTC)


def scan(gate: str, offset: int, *, accepted: bool = True) -> dict:
    return {
        "performance_id": "p1",
        "gate": gate,
        "event_time": START + timedelta(microseconds=offset),
        "accepted": accepted,
    }


class ReferenceTests(unittest.TestCase):
    def test_odd_even_singleton_rejected_and_utc(self) -> None:
        other = {**scan("gate-a", 5), "performance_id": "p2"}
        other["event_time"] = other["event_time"].astimezone(timezone(timedelta(hours=2)))
        rows = build_reference(
            [
                scan("gate-a", 101), scan("gate-a", 0),
                scan("gate-b", 90), scan("gate-b", 10), scan("gate-b", 20),
                scan("gate-a", -1, accepted=False), scan("gate-c", 0, accepted=False),
                other,
            ],
            [PERFORMANCE, {**PERFORMANCE, "performance_id": "p2", "headliner": None}],
        )
        self.assertEqual(
            [(r["performance_id"], r["gate"], r["pass_count"], r["median_event_time_utc"]) for r in rows],
            [
                ("p1", "gate-a", 2, "2026-11-19T18:00:00.000050Z"),
                ("p1", "gate-b", 3, "2026-11-19T18:00:00.000020Z"),
                ("p2", "gate-a", 1, "2026-11-19T18:00:00.000005Z"),
            ],
        )
        self.assertEqual(rows[0]["title"], "Concert")
        self.assertIsNone(rows[-1]["headliner"])

    def test_half_microsecond_before_epoch_rounds_to_earlier_instant(self) -> None:
        boundary = datetime(1970, 1, 1, tzinfo=UTC)
        rows = build_reference(
            [
                {**scan("gate-a", 0), "event_time": boundary},
                {**scan("gate-a", 0), "event_time": boundary - timedelta(microseconds=1)},
            ],
            [PERFORMANCE],
        )
        self.assertEqual(rows[0]["median_event_time_utc"], "1969-12-31T23:59:59.999999Z")

    def test_empty_or_rejected_only(self) -> None:
        self.assertEqual(build_reference([], []), [])
        self.assertEqual(build_reference([scan("gate-a", 0, accepted=False)], [PERFORMANCE]), [])

    def test_invalid_accepted_scan_and_duplicate_performance(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown performance"):
            build_reference([scan("gate-a", 0)], [])
        with self.assertRaisesRegex(ValueError, "invalid event_time"):
            invalid = {**scan("gate-a", 0), "event_time": START.replace(tzinfo=None)}
            build_reference([invalid], [PERFORMANCE])
        with self.assertRaisesRegex(ValueError, "unique"):
            build_reference([], [PERFORMANCE, PERFORMANCE])


class ComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = build_reference([scan("gate-a", 0), scan("gate-b", 0)], [PERFORMANCE])

    def test_order_independent_and_empty(self) -> None:
        compare_rows(list(reversed(self.rows)), self.rows)
        compare_rows([], [])

    def test_detects_wrong_counts_and_medians(self) -> None:
        for field, value in (("pass_count", 3), ("median_event_time_utc", "2026-11-19T18:00:00.000001Z")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Group"):
                compare_rows([{**self.rows[0], field: value}, self.rows[1]], self.rows)

    def test_detects_duplicate_and_missing_group(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            compare_rows([self.rows[0], self.rows[0]], self.rows)
        with self.assertRaisesRegex(ValueError, "missing"):
            compare_rows(self.rows[:1], self.rows)
