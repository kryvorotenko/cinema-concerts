"""Live DPC LR1 smoke/race experiment against localhost:8000 and fixture IDs."""
import asyncio
import json
import sys
import time
import uuid
import os

import httpx

BASE = "http://localhost:8000"
HEADERS = {"Authorization": "Bearer dev-token"}


async def main():
    async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=10) as client:
        health = await client.get("/health")
        assert health.status_code == 200, health.text
        prefix = str(uuid.uuid4())
        async def submit(n):
            return await client.post("/v1/scans", json={
                "scan_id": f"{prefix}-{n}", "ticket_id": f"dpc-test-ticket-{n}",
                "ticket_code": f"dpc-test-code-{n}", "gate": "test-gate",
                "sector_id": "dpc-test-sector", "event_time": "2026-11-20T12:00:00.000Z",
            })
        answers = await asyncio.gather(*(submit(n) for n in range(1, 9)))
        assert all(r.status_code == 202 for r in answers), [(r.status_code, r.text) for r in answers]
        deadline = time.monotonic() + 15
        while True:
            states = [(await client.get(f"/v1/scans/{prefix}-{n}")).json() for n in range(1, 9)]
            if all(s["state"] in ("done", "rejected", "failed") for s in states):
                break
            assert time.monotonic() < deadline, states
            await asyncio.sleep(0.1)
        sector = (await client.get("/v1/sector/dpc-test-sector")).json()
        summary = {"states": {s: sum(x["state"] == s for x in states) for s in ("done", "rejected", "failed")},
                   "inside": sector["inside"], "capacity": sector["capacity"],
                   "health_status": health.status_code}
        assert summary["states"]["failed"] == 0, states
        if os.environ.get("EXPECTED_MODE") == "locked":
            assert summary["states"]["done"] == 2 and sector["inside"] == 2, summary
            # New scan ID, same ticket: the saved decision is returned without a second effect.
            repeat = await client.post("/v1/scans", json={
                "scan_id": prefix + "-repeat", "ticket_id": states[0]["ticket_id"],
                "ticket_code": states[0]["ticket_code"], "gate": "test-gate",
                "sector_id": "dpc-test-sector", "event_time": "2026-11-20T12:00:00.000Z",
            })
            assert repeat.status_code == 202, repeat.text
            for _ in range(50):
                repeated = (await client.get(f"/v1/scans/{prefix}-repeat")).json()
                if repeated["state"] in ("done", "rejected", "failed"):
                    break
                await asyncio.sleep(0.1)
            assert repeated["decision"] == states[0]["decision"], repeated
            assert (await client.get("/v1/sector/dpc-test-sector")).json()["inside"] == 2
        elif os.environ.get("EXPECTED_MODE") == "unprotected":
            assert summary["states"]["done"] > sector["capacity"] or sector["inside"] > sector["capacity"], summary
        print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
