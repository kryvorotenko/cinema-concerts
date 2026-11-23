"""Live Ray receiver/retry experiment; EXPECT_RETRY=1 requires an armed one-shot fault."""
import os
import time
import uuid

import httpx


def main():
    scan_id = "dpc-ray-" + str(uuid.uuid4())
    payload = {"scan_id": scan_id, "ticket_id": "dpc-test-ticket-1",
               "ticket_code": "dpc-test-code-1", "gate": "ray-gate",
               "sector_id": "dpc-test-sector", "event_time": "2026-11-23T18:00:00.000Z"}
    with httpx.Client(base_url="http://localhost:8000", headers={"Authorization": "Bearer dev-token"}, timeout=10) as client:
        response = client.post("/v1/scans", json=payload)
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            row = client.get(f"/v1/scans/{scan_id}").json()
            if row["state"] in ("done", "rejected", "failed"):
                if os.environ.get("EXPECT_RETRY") != "1" or row["receiver_calls"] >= 2 or row["state"] == "failed":
                    break
            time.sleep(0.25)
        assert row["state"] == "done", row
        expected_calls = 2 if os.environ.get("EXPECT_RETRY") == "1" else 1
        assert row["receiver_calls"] >= expected_calls, row
        sector = client.get("/v1/sector/dpc-test-sector").json()
        assert sector["inside"] == 1, sector
        repeat_id = "dpc-ray-" + str(uuid.uuid4())
        repeated = client.post("/v1/scans", json={**payload, "scan_id": repeat_id})
        assert repeated.status_code == 202, repeated.text
        repeat_deadline = time.monotonic() + 30
        while time.monotonic() < repeat_deadline:
            repeat_row = client.get(f"/v1/scans/{repeat_id}").json()
            if repeat_row["state"] in ("done", "rejected", "failed"):
                break
            time.sleep(0.25)
        assert repeat_row["state"] == "done" and repeat_row["decision"] == row["decision"], repeat_row
        assert client.get("/v1/sector/dpc-test-sector").json()["inside"] == 1
        print({"scan_id": scan_id, "state": row["state"], "receiver_calls": row["receiver_calls"],
               "inside": sector["inside"], "capacity": sector["capacity"],
               "new_scan_same_ticket": repeat_row["state"]})


if __name__ == "__main__":
    main()
