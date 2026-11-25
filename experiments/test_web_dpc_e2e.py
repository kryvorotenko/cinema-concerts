"""Web <-> DPC end to end: the DPC scan queue checks tickets through the Web ticket API.

Needs the whole stack with DPC in its default TICKET_CHECK_MODE=web (docker compose up -d --build),
the Web demo data (migration 020) and the e2e sectors:

    Get-Content -Raw experiments/web_dpc_e2e_prepare.sql | docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U app -d app
    python experiments/test_web_dpc_e2e.py

Run the prepare script again before every repeat. Environment: DPC_BASE (default http://localhost:8000),
API_TOKEN (default dev-token). Needs only `httpx`.
"""

import os
import sys
import time
import uuid

import httpx

DPC = os.environ.get("DPC_BASE", "http://localhost:8000")
HEADERS = {"Authorization": "Bearer " + os.environ.get("API_TOKEN", "dev-token")}
RUN = uuid.uuid4().hex[:8]
passed = 0


def check(condition: bool, what: str, detail: object = "") -> None:
    global passed
    if not condition:
        sys.exit(f"FAIL {what} {detail}")
    passed += 1
    print(f"ok   {what}")


def scan(ticket_id: str, code: str, sector: str) -> dict:
    body = {
        "scan_id": f"e2e-{RUN}-{uuid.uuid4().hex[:6]}",
        "ticket_id": ticket_id,
        "ticket_code": code,
        "gate": "gate-1",
        "sector_id": sector,
        "event_time": "2035-06-01T16:30:00.000Z",
    }
    reply = httpx.post(f"{DPC}/v1/scans", json=body, headers=HEADERS, timeout=10)
    check(reply.status_code == 202, f"scan of {code or ticket_id} on {sector} accepted into the queue", reply.text)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = httpx.get(f"{DPC}/v1/scans/{body['scan_id']}", headers=HEADERS, timeout=10).json()
        if state["state"] in ("done", "rejected", "failed"):
            return state
        time.sleep(0.1)
    sys.exit(f"FAIL scan {body['scan_id']} did not finish: {state}")


def inside(sector: str) -> int:
    return httpx.get(f"{DPC}/v1/sector/{sector}", headers=HEADERS, timeout=10).json()["inside"]


first = scan("tkt-demo-1", "TKT-DEMO-0001", "e2e-sector-jazz")
check(first["state"] == "done" and first["decision"]["accepted"], "valid ticket (Web says valid=true) is let in", first)
check(inside("e2e-sector-jazz") == 1, "sector counter went up by one")

again = scan("tkt-demo-1", "TKT-DEMO-0001", "e2e-sector-jazz")
check(again["decision"] == first["decision"] and inside("e2e-sector-jazz") == 1,
      "the same ticket under a new scan_id: same decision, no second entry")

refunded = scan("tkt-demo-2", "TKT-DEMO-0002", "e2e-sector-jazz")
check(refunded["state"] == "rejected" and refunded["decision"]["reason"] == "invalid_ticket",
      "refunded ticket (Web says valid=false) is refused", refunded)

unknown = scan("tkt-unknown", "NO-SUCH-CODE", "e2e-sector-jazz")
check(unknown["state"] == "rejected" and unknown["decision"]["reason"] == "invalid_ticket",
      "unknown code (Web answers 404) is refused", unknown)

mismatch = scan("tkt-someone-else", "TKT-DEMO-0001", "e2e-sector-jazz")
check(mismatch["state"] == "rejected" and mismatch["decision"]["reason"] == "invalid_ticket",
      "a code that belongs to another ticket_id is refused", mismatch)

foreign = scan("tkt-demo-3", "TKT-DEMO-0003", "e2e-sector-jazz")
check(foreign["state"] == "rejected" and foreign["decision"]["reason"] == "wrong_performance",
      "a valid film ticket in a jazz sector: wrong_performance", foreign)
check(inside("e2e-sector-jazz") == 1, "the refusals did not change the counter")

print(f"\n{passed} checks passed against {DPC}")
