"""Reproducible full-queue/health probe: API with WORKERS=1 QUEUE_CAPACITY=1."""
import asyncio
import json
import statistics
import time
import uuid

import httpx


async def main():
    async with (httpx.AsyncClient(base_url="http://localhost:8000", headers={"Authorization": "Bearer dev-token"}, timeout=10) as client,
                httpx.AsyncClient(base_url="http://localhost:8000", timeout=10) as health_client):
        prefix = str(uuid.uuid4())
        async def send(i, batch):
            return await client.post("/v1/scans", json={
                "scan_id": f"{prefix}-{batch}-{i}", "ticket_id": f"dpc-test-ticket-{i}",
                "ticket_code": f"dpc-test-code-{i}", "gate": "test-gate",
                "sector_id": "dpc-test-sector", "event_time": "2026-11-20T12:00:00.000Z"})
        health_ms = []
        responses = []
        deadline = time.monotonic() + 5
        async def health_probe():
            while time.monotonic() < deadline:
                t = time.monotonic()
                r = await health_client.get("/health")
                assert r.status_code == 200
                health_ms.append((time.monotonic() - t) * 1000)
                await asyncio.sleep(0.03)
        async def load():
            batch = 0
            while time.monotonic() < deadline:
                responses.extend(await asyncio.gather(*(send(i, batch) for i in range(10, 30))))
                batch += 1
                await asyncio.sleep(0.05)
        await asyncio.gather(health_probe(), load())
        accepted = sum(r.status_code == 202 for r in responses)
        refused = [r for r in responses if r.status_code == 429]
        assert refused and accepted, (accepted, len(refused))
        assert all(r.headers.get("Retry-After") == "1" for r in refused)
        p95 = statistics.quantiles(health_ms, n=100, method="inclusive")[94]
        result = {"duration_s": 5, "capacity": 1, "workers": 1, "concurrent_clients": 20,
                  "accepted": accepted, "refused_429": len(refused), "health_samples": len(health_ms),
                  "health_p95_ms": round(p95, 2)}
        print(json.dumps(result))
        assert p95 <= 100, result


if __name__ == "__main__":
    asyncio.run(main())
