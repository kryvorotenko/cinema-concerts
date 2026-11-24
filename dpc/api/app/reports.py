"""C01 batch report routes backed by the existing Spark runner and shared volume."""

import json
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Response

from . import config
from .auth import require_token
from .problems import Problem

DATA_DIR = Path("/data/c01-lab4")
REPORTS_DIR = DATA_DIR / "reports"
REFERENCE_FILE = DATA_DIR / "reference.json"
JOB = {
    "script": "report.py",
    "args": [
        "--facts", (DATA_DIR / "scans").as_posix(),
        "--dim", (DATA_DIR / "performances").as_posix(),
        "--out", (REPORTS_DIR / "{run}").as_posix(),
        "--partitions", "4",
    ],
}
RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}")
router = APIRouter(prefix="/v1/reports/main", dependencies=[Depends(require_token)])


def runner_request(method: str, payload: dict | None = None) -> dict | list:
    try:
        response = httpx.request(
            method, f"{config.RUNNER_URL.rstrip('/')}/jobs", json=payload, timeout=5.0, trust_env=False
        )
    except httpx.RequestError as exc:
        raise Problem(503, "spark-runner-unavailable", "Spark runner unavailable") from exc
    if method == "POST" and response.status_code == 409:
        raise Problem(409, "report-running", "A report is already running")
    if response.status_code != (202 if method == "POST" else 200):
        raise Problem(502, "spark-runner-error", "Spark runner returned an unexpected status")
    try:
        return response.json()
    except ValueError as exc:
        raise Problem(502, "spark-runner-error", "Spark runner returned invalid JSON") from exc


def run_status(job: dict) -> dict:
    run = job.get("run")
    state = job.get("state")
    if not isinstance(run, str) or RUN_ID.fullmatch(run) is None or state not in ("running", "done", "failed"):
        raise Problem(502, "spark-runner-error", "Spark runner returned an invalid report status")
    return {"state": state, "run": run, "result": None}


@router.post("/refresh", status_code=202)
def refresh_report(response: Response) -> dict:
    job = runner_request("POST", JOB)
    if not isinstance(job, dict):
        raise Problem(502, "spark-runner-error", "Spark runner returned an invalid report status")
    response.headers["Location"] = "/v1/reports/main"
    return run_status(job)


@router.get("")
def get_report() -> dict:
    payload = runner_request("GET")
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise Problem(502, "spark-runner-error", "Spark runner returned an invalid job list")
    for job in jobs:  
        if isinstance(job, dict) and job.get("script") == JOB["script"] and job.get("args") == JOB["args"]:
            status = run_status(job)
            if status["state"] == "done":
                directory = REPORTS_DIR / status["run"]
                try:
                    if not (directory / "_SUCCESS").is_file():
                        raise FileNotFoundError(directory)
                    rows = []
                    for path in sorted(directory.glob("part-*.json")):
                        with path.open(encoding="utf-8") as part:
                            rows.extend(json.loads(line) for line in part if line.strip())
                    status["result"] = {"rows": rows}
                except (OSError, ValueError) as exc:
                    raise Problem(500, "report-result-unreadable", "Report result cannot be read") from exc
            return status
    return {"state": "idle", "run": None, "result": None}


@router.get("/reference")
def get_reference() -> dict:
    try:
        return json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Problem(404, "report-reference-missing", "Prepare the independent Parquet reference first") from exc
    except (OSError, ValueError) as exc:
        raise Problem(500, "report-reference-unreadable", "Report reference cannot be read") from exc
