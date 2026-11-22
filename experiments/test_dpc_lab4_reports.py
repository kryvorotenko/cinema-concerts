"""Test the Lab 4 report status against the runner's GET /jobs contract."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dpc.api.app import config, problems, reports
from dpc.spark import runner

RUN = "20261123-120000-a1b2c3"


def report_job(state: str) -> dict:
    return {**reports.JOB, "run": RUN, "state": state, "log": []}


class ReportStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        problems.install(app)
        app.include_router(reports.router)
        self.client = TestClient(app, headers={"Authorization": f"Bearer {config.API_TOKEN}"})
        self.addCleanup(self.client.close)

    def get_status(self, response: httpx.Response) -> httpx.Response:
        with patch.object(reports.httpx, "request", return_value=response) as request:
            result = self.client.get("/v1/reports/main")
        request.assert_called_once_with(
            "GET", f"{config.RUNNER_URL.rstrip('/')}/jobs", json=None, timeout=5.0, trust_env=False
        )
        return result

    def status_for_jobs(self, jobs: list[dict]) -> httpx.Response:
        handler = object.__new__(runner.Handler)
        handler.path = "/jobs"
        with patch.object(runner.store, "all", return_value=jobs), patch.object(handler, "_send") as send:
            handler.do_GET()
        status, payload = send.call_args.args
        return self.get_status(httpx.Response(status, json=payload))

    def test_finds_latest_matching_running_report(self) -> None:
        unrelated_script = {**report_job("done"), "script": "smoke_parquet.py"}
        unrelated_args = {**report_job("done"), "args": ["--out", "/data/other"]}
        older_report = {**report_job("failed"), "run": "20261123-110000-a1b2c3"}
        response = self.status_for_jobs([unrelated_script, unrelated_args, report_job("running"), older_report])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"state": "running", "run": RUN, "result": None})

    def test_done_report_loads_result(self) -> None:
        row = {"performance_id": "p1", "gate": "gate-a", "pass_count": 3,
               "median_event_time_utc": "2026-11-23T12:00:00.000000Z"}
        with TemporaryDirectory() as folder:
            directory = Path(folder) / RUN
            directory.mkdir()
            (directory / "_SUCCESS").touch()
            (directory / "part-00000.json").write_text(json.dumps(row) + "\n", encoding="utf-8")
            with patch.object(reports, "REPORTS_DIR", Path(folder)):
                response = self.status_for_jobs([report_job("done")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"state": "done", "run": RUN, "result": {"rows": [row]}})

    def test_failed_report(self) -> None:
        response = self.status_for_jobs([report_job("failed")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"state": "failed", "run": RUN, "result": None})

    def test_idle_for_empty_or_unrelated_jobs(self) -> None:
        for jobs in ([], [{**report_job("failed"), "script": "another.py"}]):
            with self.subTest(jobs=jobs):
                response = self.status_for_jobs(jobs)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"state": "idle", "run": None, "result": None})

    def test_invalid_job_envelopes_return_502(self) -> None:
        for payload in ([], {}, {"jobs": None}, {"jobs": {}}):
            with self.subTest(payload=payload):
                response = self.get_status(httpx.Response(200, json=payload))
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["title"], "Spark runner returned an invalid job list")

    def test_invalid_matching_status_returns_502(self) -> None:
        response = self.status_for_jobs([report_job("unknown")])
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["title"], "Spark runner returned an invalid report status")


class RunnerArgumentsTests(unittest.TestCase):
    def test_run_substitution_is_only_applied_to_submit_command(self) -> None:
        store = runner.JobStore()
        jobs_dir = Path(runner.__file__).with_name("jobs")
        with patch.object(runner, "JOBS_DIR", jobs_dir), patch.object(runner.threading, "Thread") as thread:
            job = store.start(reports.JOB["script"], reports.JOB["args"], [])
        _, command = thread.call_args.kwargs["args"]
        output = reports.JOB["args"][reports.JOB["args"].index("--out") + 1]
        self.assertIn("{run}", output)
        self.assertEqual(store.all()[0]["args"], reports.JOB["args"])
        self.assertIn(output, store.all()[0]["args"])
        self.assertIn(output.replace("{run}", job["run"]), command)
        self.assertNotIn(output, command)
