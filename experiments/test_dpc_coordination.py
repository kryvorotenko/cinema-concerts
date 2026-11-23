"""Live O6.1/O6.2: two leaders, lease failover, fenced assignments."""
import json
import subprocess
import time
import uuid

import httpx

BASE = "http://localhost:8000"
CLIENT = {"Authorization": "Bearer dev-token"}
WEB = {"Authorization": "Bearer dev-web-reserve-token"}
COORD = {"Authorization": "Bearer dev-coordinator-token"}


def docker(*args):
    subprocess.run(["docker", "compose", *args], check=True, stdout=subprocess.DEVNULL)


def seed_buyers(prefix):
    rows = []
    for number in (1, 2):
        buyer = f"{prefix}-buyer-{number}"
        rows.append(f"('{buyer}','{buyer}@example.invalid','Fixture buyer','unused')")
    sql = "INSERT INTO users(id,email,display_name,password_hash) VALUES " + ",".join(rows) + " ON CONFLICT DO NOTHING;"
    subprocess.run(["docker", "compose", "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
                    "-U", "app", "-d", "app"], input=sql, text=True, check=True, stdout=subprocess.DEVNULL)


def wait_until(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("condition not reached within timeout")


def main():
    prefix = "dpc-test-" + str(uuid.uuid4())
    seed_buyers(prefix)
    with httpx.Client(base_url=BASE, timeout=5) as client:
        def ready():
            try:
                return client.get("/health").status_code == 200
            except httpx.TransportError:
                return False
        wait_until(ready)
        assert client.get("/internal/coordinator/next", headers=CLIENT).status_code == 401
        assert client.post("/internal/waitlist/reserves", headers=CLIENT, json={
            "web_reserve_id": "unauthorized", "performance_id": "dpc-test-performance",
            "seat_id": "unauthorized"}).status_code == 401
        def status():
            return client.get("/v1/coordinator", headers=CLIENT).json()

        first = wait_until(lambda: status() if status()["owner"] else None)
        assert first["generation"] > 0, first

        def enqueue(number):
            wait_id = f"{prefix}-wait-{number}"
            reserve_id = f"{prefix}-reserve-{number}"
            joined = client.post("/v1/waitlist", headers=CLIENT, json={
                "waitlist_id": wait_id, "performance_id": "dpc-test-performance",
                "buyer_id": f"{prefix}-buyer-{number}"})
            assert joined.status_code == 201, joined.text
            reserved = client.post("/internal/waitlist/reserves", headers=WEB, json={
                "web_reserve_id": reserve_id, "performance_id": "dpc-test-performance",
                "seat_id": f"{prefix}-seat-{number}"})
            assert reserved.status_code == 201, reserved.text
            return wait_id, reserve_id

        wait1, reserve1 = enqueue(1)
        def assigned(reserve_id):
            items = client.get("/v1/history", headers=CLIENT).json()["items"]
            return next((x for x in items if x["kind"] == "assigned" and x["web_reserve_id"] == reserve_id), None)
        first_assignment = wait_until(lambda: assigned(reserve1))
        assert first_assignment["generation"] == first["generation"]

        old = first["owner"]
        docker("pause", old)
        paused_at = time.monotonic()
        try:
            second = wait_until(lambda: (s if s["owner"] != old and s["generation"] > first["generation"] else None)
                                if (s := status()) else None, timeout=20)
            failover_s = time.monotonic() - paused_at
            stale = client.post("/internal/coordinator/assign", headers=COORD, json={
                "owner": old, "generation": first["generation"],
                "assignment_id": f"{prefix}-stale", "web_reserve_id": f"{prefix}-missing",
                "waitlist_id": f"{prefix}-missing"})
            assert stale.status_code == 409, stale.text
            wait2, reserve2 = enqueue(2)
            second_assignment = wait_until(lambda: assigned(reserve2))
            assert second_assignment["generation"] == second["generation"]
            web_result = client.get(f"/internal/waitlist/assignments/{reserve2}", headers=WEB)
            assert web_result.status_code == 200, web_result.text
            assert web_result.json()["assignment_id"] == "assignment:" + reserve2
            unregistered = client.post("/internal/coordinator/assign", headers=COORD, json={
                "owner": "unregistered", "generation": second["generation"] + 999,
                "assignment_id": f"{prefix}-future", "web_reserve_id": reserve2,
                "waitlist_id": wait2})
            assert unregistered.status_code == 409, unregistered.text
            replay = client.post("/internal/coordinator/assign", headers=COORD, json={
                "owner": second["owner"], "generation": second["generation"],
                "assignment_id": "assignment:" + reserve2,
                "web_reserve_id": reserve2, "waitlist_id": wait2})
            assert replay.status_code == 200 and replay.json()["replayed"] is True, replay.text
        finally:
            docker("unpause", old)

        time.sleep(2)
        history = client.get("/v1/history", headers=CLIENT).json()["items"]
        new_register_id = next(x["id"] for x in history if x["kind"] == "register"
                               and x["generation"] == second["generation"])
        assert not [x for x in history if x["id"] > new_register_id and x["kind"] == "assigned"
                    and x["generation"] < second["generation"]], history
        assert len([x for x in history if x["kind"] == "assigned" and x["web_reserve_id"] in (reserve1,reserve2)]) == 2
        print(json.dumps({"first": first, "second": second, "failover_s": round(failover_s, 3),
                          "first_assignment": first_assignment["generation"],
                          "second_assignment": second_assignment["generation"],
                          "stale_status": stale.status_code,
                          "unregistered_status": unregistered.status_code,
                          "replayed": replay.json()["replayed"],
                          "web_assignment_id": web_result.json()["assignment_id"],
                          "history_rows": len(history)}))


if __name__ == "__main__":
    main()
