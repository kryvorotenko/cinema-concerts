import asyncio
import os
import re
import uuid

import httpx

BASES = os.environ.get("BASES", os.environ.get("BASE", "http://localhost:8080")).split(",")
SERVICE = {"Authorization": "Bearer " + os.environ.get("WEB_API_TOKEN", "dev-token")}
PROBLEM = "application/problem+json"


def session(login: str, password: str) -> dict[str, str]:
    reply = httpx.post(BASES[0] + "/v1/auth/login", json={"login": login, "password": password}, timeout=15)
    reply.raise_for_status()
    return {"Cookie": f"session={reply.cookies['session']}"}

ALICE = session("alice@example.invalid", "alice-pass")
BOB = session("bob@example.invalid", "bob-pass")


def fresh(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": uuid.uuid4().hex}

passed = 0


def check(condition: bool, what: str, reply: httpx.Response | None = None) -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAIL {what}" + (f": {reply.status_code} {reply.text}" if reply is not None else ""))
    passed += 1
    print(f"ok   {what}")


def is_problem(reply: httpx.Response, status: int) -> bool:
    body = reply.json() if reply.headers.get("content-type", "").startswith(PROBLEM) else {}
    return reply.status_code == status and body.get("status") == status and "title" in body and "type" in body


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASES[0], timeout=15) as c:
        r = await c.get("/health")
        check(r.status_code == 200 and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", r.headers.get("x-request-id", "")),
              "O1.6 /health answers and carries X-Request-ID", r)
        r = await c.get("/health", headers={"X-Request-ID": "my-id-1"})
        check(r.headers.get("x-request-id") == "my-id-1", "O1.6 a sane incoming X-Request-ID is returned as is", r)

        r = await c.get("/v1/events")
        check(is_problem(r, 401), "no session -> 401 Problem Details", r)
        r = await c.get("/v1/events", headers={"X-User-Id": "nobody"})
        check(is_problem(r, 401), "unknown X-User-Id is not an identity -> 401", r)

        events = (await c.get("/v1/events", headers=ALICE)).json()["items"]
        check(any(e["id"] == "scr-jazz-1" for e in events), "GET /v1/events lists performances (id = performance_id)")
        r = await c.get("/v1/events/scr-jazz-1/categories", headers=ALICE)
        cats = {x["id"]: x for x in r.json()["items"]}
        check(r.status_code == 200 and cats["cat-jazz-std"]["price"] == {"amount_minor": 60000, "currency": "UAH"},
              "categories carry price as integer minor units + currency", r)
        check(is_problem(await c.get("/v1/events/no-such/categories", headers=ALICE), 404), "unknown performance -> 404")

        before = cats["cat-jazz-std"]["available"]
        r = await c.post("/v1/holds", headers=fresh(ALICE), json={"category_id": "cat-jazz-std", "seats": 2})
        check(r.status_code == 201 and r.headers["location"] == f"/v1/holds/{r.json()['id']}", "POST /v1/holds -> 201 + Location", r)
        hold = r.json()
        check(hold["status"] == "held" and hold["seats"] == 2 and hold["version"] == 1 and isinstance(hold["id"], str),
              "hold is held, version 1, id is a string")
        check(hold["total"] == {"amount_minor": 120000, "currency": "UAH"}, "total = seats * price in minor units")
        r = await c.get(f"/v1/holds/{hold['id']}", headers=ALICE)
        check(r.status_code == 200 and r.json() == hold and r.headers.get("etag") == '"1"', "GET /v1/holds/{id} returns the hold + ETag", r)
        after = {x["id"]: x for x in (await c.get("/v1/events/scr-jazz-1/categories", headers=ALICE)).json()["items"]}
        check(after["cat-jazz-std"]["available"] == before - 2, "available went down by the held seats")
        r = await c.get(f"/v1/holds/{hold['id']}", headers=BOB)
        check(is_problem(r, 404), "someone else's hold -> 404 (same as a missing one)", r)
        check(is_problem(await c.get("/v1/holds/missing", headers=ALICE), 404), "missing hold -> 404")

        r = await c.post("/v1/holds", headers=fresh({**ALICE, "Content-Type": "application/json"}), content=b'{"category_id": ')
        check(is_problem(r, 400), "broken JSON -> 400", r)
        for bad in ({"category_id": "cat-jazz-std", "seats": 0}, {"category_id": "cat-jazz-std", "seats": "2"},
                    {"category_id": "cat-jazz-std"}, {"seats": 1},
                    {"category_id": "cat-jazz-std", "seats": 1, "user_id": "usr-bob"},
                    {"category_id": "cat-jazz-std", "seats": 1, "status": "confirmed"}):
            r = await c.post("/v1/holds", headers=fresh(ALICE), json=bad)
            check(is_problem(r, 422), f"invalid data {bad} -> 422", r)
        check(is_problem(await c.post("/v1/holds", headers=fresh(ALICE), json={"category_id": "no-such", "seats": 1}), 404),
              "unknown category -> 404")
        r = await c.post("/v1/holds", headers=fresh(ALICE), json={"category_id": "cat-scarce", "seats": 6})
        check(is_problem(r, 409) and r.json()["type"].endswith("not-enough-seats"), "more seats than available -> 409", r)
        r = await c.post("/v1/holds", headers=fresh(ALICE), json={"category_id": "cat-closed", "seats": 1})
        check(is_problem(r, 409) and r.json()["type"].endswith("sales-closed"), "sales closed -> 409", r)

        ids = []
        for _ in range(5):
            r = await c.post("/v1/holds", headers=fresh(BOB), json={"category_id": "cat-film-std", "seats": 1})
            ids.append(r.json()["id"])
        seen, cursor, pages = [], None, 0
        while True:
            r = await c.get("/v1/holds", headers=BOB, params={"limit": 2, **({"cursor": cursor} if cursor else {})})
            check(r.status_code == 200 and len(r.json()["items"]) <= 2, f"page {pages + 1} has at most 2 items", r)
            seen += [h["id"] for h in r.json()["items"]]
            cursor, pages = r.json()["next_cursor"], pages + 1
            if cursor is None:
                break
        check(seen == ids[::-1] + ["bk-demo-2"] and pages == 3,
              "all pages together = my holds, newest first, none repeated or lost")
        check(hold["id"] not in seen, "the list shows only my own holds")
        for bad in ("garbage", "e30", ""):
            r = await c.get("/v1/holds", headers=BOB, params={"cursor": bad})
            if bad:
                check(is_problem(r, 400), f"broken cursor {bad!r} -> 400", r)
        for limit in (0, 51):
            check(is_problem(await c.get("/v1/holds", headers=BOB, params={"limit": limit}), 422), f"limit={limit} -> 422")

        r = await c.get("/v1/tickets/TKT-DEMO-0001", headers=SERVICE)
        check(r.status_code == 200 and r.json() == {"ticket_id": "tkt-demo-1", "performance_id": "scr-jazz-1", "valid": True},
              "GET /v1/tickets/{code} -> ticket_id, performance_id, valid=true", r)
        r = await c.get("/v1/tickets/TKT-DEMO-0002", headers=SERVICE)
        check(r.status_code == 200 and r.json()["valid"] is False, "refunded ticket -> valid=false", r)
        r = await c.get("/v1/tickets/tkt-demo-1", headers=SERVICE)
        check(r.status_code == 200 and r.json() == {"ticket_id": "tkt-demo-1", "performance_id": "scr-jazz-1", "valid": True},
              "the ticket id works in place of the code (a scan that carries only ticket_id)", r)
        r = await c.get("/v1/tickets/TKT-DEMO-0003", headers=SERVICE)
        check(r.status_code == 200 and r.json() == {"ticket_id": "tkt-demo-3", "performance_id": "scr-film-1", "valid": True},
              "a valid ticket of another performance (film) is told apart", r)
        check(is_problem(await c.get("/v1/tickets/NOPE", headers=SERVICE), 404), "unknown ticket code -> 404")
        check(is_problem(await c.get("/v1/tickets/TKT-DEMO-0001"), 401), "ticket check without service token -> 401")
        check(is_problem(await c.get("/v1/tickets/TKT-DEMO-0001", headers=ALICE), 401), "a user header is not a service token -> 401")

    async def hold(base: str) -> int:
        async with httpx.AsyncClient(base_url=base, timeout=15) as c:
            return (await c.post("/v1/holds", headers=fresh(ALICE), json={"category_id": "cat-scarce", "seats": 1})).status_code

    codes = await asyncio.gather(*(hold(BASES[i % len(BASES)]) for i in range(20)))
    async with httpx.AsyncClient(base_url=BASES[0], timeout=15) as c:
        scarce = {x["id"]: x for x in (await c.get("/v1/events/scr-jazz-1/categories", headers=ALICE)).json()["items"]}["cat-scarce"]
    check(codes.count(201) == 5 and codes.count(409) == 15 and scarce["available"] == 0,
          f"20 parallel holds on 5 seats: {codes.count(201)}x201, {codes.count(409)}x409, available={scarce['available']}")
    print(f"\n{passed} checks passed against {', '.join(BASES)}")


asyncio.run(main())
