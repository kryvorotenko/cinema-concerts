"""Two identical lease-based coordinators; PostgreSQL fences their writes."""

import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

from etcd import Etcd, b64

INSTANCE = os.environ.get("INSTANCE", "coordinator")
ETCD_URL = os.environ.get("ETCD_URL", "http://localhost:2379")
API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
COORDINATOR_TOKEN = os.environ.get("COORDINATOR_TOKEN", "dev-coordinator-token")
LEASE_TTL_S = int(os.environ.get("LEASE_TTL_S", "5"))
ROLE_KEY = "/roles/assigner"
stop = threading.Event()


def log(event: str, **fields: object) -> None:
    line = {"time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "instance": INSTANCE, "event": event}
    sys.stdout.write(json.dumps({**line, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def api(method: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        API_URL + path, data=body, method=method,
        headers={"Authorization": f"Bearer {COORDINATOR_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=3) as reply:
        return json.loads(reply.read() or b"{}")


def acquire(client: Etcd) -> tuple[str, int] | None:
    lease = client.grant(LEASE_TTL_S)
    answer = client.txn(
        compare=[{"key": b64(ROLE_KEY), "target": "CREATE", "create_revision": 0, "result": "EQUAL"}],
        success=[{"request_put": {"key": b64(ROLE_KEY), "value": b64(INSTANCE), "lease": lease}}],
    )
    if not answer.get("succeeded"):
        client.revoke(lease)
        return None
    role = client.get(ROLE_KEY)
    if role is None or role["value"] != INSTANCE:
        client.revoke(lease)
        return None
    generation = role["create_revision"]
    try:
        api("POST", "/internal/coordinator/register", {"owner": INSTANCE, "generation": generation})
    except Exception:
        client.revoke(lease)
        raise
    log("coordinator.acquired", generation=generation, lease_ttl_s=LEASE_TTL_S)
    return lease, generation


def lead(client: Etcd, lease: str, generation: int) -> None:
    next_renewal = time.monotonic()
    while not stop.is_set():
        if time.monotonic() >= next_renewal:
            if client.keepalive(lease) <= 0:
                log("coordinator.lease_lost", generation=generation)
                return
            role = client.get(ROLE_KEY)
            if role is None or role["value"] != INSTANCE or role["create_revision"] != generation:
                log("coordinator.role_lost", generation=generation)
                return
            next_renewal = time.monotonic() + max(0.5, LEASE_TTL_S / 3)
        candidate = api("GET", "/internal/coordinator/next")
        reserve = candidate.get("web_reserve_id")
        if reserve:
            try:
                result = api("POST", "/internal/coordinator/assign", {
                    "owner": INSTANCE, "generation": generation,
                    "assignment_id": "assignment:" + reserve,
                    "web_reserve_id": reserve, "waitlist_id": candidate["waitlist_id"],
                })
                log("coordinator.assigned", generation=generation, assignment_id=result["assignment_id"])
            except urllib.error.HTTPError as exc:
                log("coordinator.assignment_rejected", generation=generation, status=exc.code)
        stop.wait(0.3)


def main() -> None:
    if not 1 <= LEASE_TTL_S <= 5:
        raise ValueError("LEASE_TTL_S must be 1..5")
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    client = Etcd(ETCD_URL)
    log("coordinator.started", lease_ttl_s=LEASE_TTL_S)
    while not stop.is_set():
        try:
            acquired = acquire(client)
            if acquired:
                lease, generation = acquired
                try:
                    lead(client, lease, generation)
                finally:
                    client.revoke(lease)
                    log("coordinator.released", generation=generation)
        except (OSError, KeyError, ValueError, urllib.error.HTTPError) as exc:
            log("coordinator.retry", error=type(exc).__name__)
        stop.wait(0.5)
    log("coordinator.stopped")


if __name__ == "__main__":
    main()
