import asyncio
import json
import os
import random
import sys
import time
import uuid

import httpx

BASES = os.environ.get("BASES", os.environ.get("BASE", "http://localhost:8080")).split(",")
DATABASE_URL = os.environ.get("DATABASE_URL")
BUYERS = int(os.environ.get("BUYERS", "300"))
PROBLEM = "application/problem+json"


def session(login: str, password: str) -> dict[str, str]:
    reply = httpx.post(BASES[0] + "/v1/auth/login", json={"login": login, "password": password}, timeout=15)
    reply.raise_for_status()
    return {"Cookie": f"session={reply.cookies['session']}"}

USERS = [
    session("alice@example.invalid", "alice-pass"),
    session("bob@example.invalid", "bob-pass"),
    session("staff@example.invalid", "staff-pass"),
]
ALICE, BOB = USERS[0], USERS[1]
passed = 0


def check(condition: bool, what: str, reply: httpx.Response | None = None) -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAIL {what}" + (f": {reply.status_code} {reply.text}" if reply is not None else ""))
    passed += 1
    print(f"ok   {what}")


def is_problem(reply: httpx.Response, status: int, slug: str | None = None) -> bool:
    if not reply.headers.get("content-type", "").startswith(PROBLEM):
        return False
    body = reply.json()
    return reply.status_code == status and body.get("status") == status and (slug is None or body["type"].endswith(slug))


def new_key() -> str:
    return uuid.uuid4().hex


def body(category: str, seats: int = 1) -> dict:
    return {"category_id": category, "seats": seats}


async def available(c: httpx.AsyncClient, category: str) -> int:
    reply = await c.get("/v1/events/scr-jazz-1/categories", headers=ALICE)
    return {x["id"]: x for x in reply.json()["items"]}[category]["available"]


async def post_hold(c: httpx.AsyncClient, user: dict, payload: dict, key: str | None, **extra) -> httpx.Response:
    headers = {**user, **({"Idempotency-Key": key} if key is not None else {})}
    return await c.post("/v1/holds", headers=headers, json=payload, **extra)


async def buy_with_retries(base: str, user: dict, category: str, stats: dict) -> int:
    key = new_key()
    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        for attempt in range(8):
            try:
                reply = await post_hold(c, user, body(category), key)
            except httpx.TransportError:
                stats["transport_errors"] += 1
                await asyncio.sleep(0.2 + random.random() * 0.2)
                continue
            if reply.status_code in (503, 409) and (reply.status_code == 503 or reply.json()["type"].endswith("request-in-progress")):
                stats["retries"] += 1
                await asyncio.sleep(float(reply.headers.get("retry-after", "1")) * (0.5 + random.random() * 0.5))
                continue
            return reply.status_code
    return 0


def db_query(sql: str, params: tuple = ()) -> list:
    import psycopg

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


async def functional() -> None:
    async with httpx.AsyncClient(base_url=BASES[0], timeout=15) as c:
        r = await c.post("/v1/holds", json=body("cat-jazz-std"))
        check(is_problem(r, 401), "no user and no key -> 401 first", r)
        r = await post_hold(c, ALICE, body("cat-jazz-std"), None)
        check(is_problem(r, 400, "idempotency-key-required"), "O2.2 no Idempotency-Key -> 400", r)
        r = await c.post("/v1/holds", headers={**ALICE, "Idempotency-Key": ""}, json=body("cat-jazz-std"))
        check(is_problem(r, 400), "O2.2 empty Idempotency-Key -> 400", r)
        r = await post_hold(c, ALICE, body("cat-jazz-std"), "k" * 256)
        check(is_problem(r, 400, "idempotency-key-invalid"), "O2.2 key longer than 255 -> 400", r)
        r = await post_hold(c, ALICE, body("cat-jazz-std"), "has space")
        check(is_problem(r, 400, "idempotency-key-invalid"), "O2.2 key with a space -> 400", r)
        r = await c.post("/v1/holds", headers={**ALICE, "Idempotency-Key": new_key()}, json={"category_id": "cat-jazz-std", "seats": "2"})
        check(is_problem(r, 422), "a valid key does not hide a bad body -> 422", r)

        before = await available(c, "cat-jazz-std")
        key = new_key()
        first = await post_hold(c, ALICE, body("cat-jazz-std", 2), key)
        check(first.status_code == 201 and "idempotent-replayed" not in first.headers, "first request with a key -> 201, not a replay", first)
        second = await post_hold(c, ALICE, body("cat-jazz-std", 2), key)
        check(second.status_code == 201 and second.json() == first.json(), "O2.2 same key, same body -> the same answer", second)
        check(second.headers.get("idempotent-replayed") == "true", "the repeated answer is marked Idempotent-Replayed")
        check(second.headers.get("location") == first.headers["location"] and second.headers.get("etag") == first.headers["etag"],
              "Location and ETag are replayed too")
        check(await available(c, "cat-jazz-std") == before - 2, "the effect happened once: seats taken once")

        reordered = await c.post("/v1/holds", headers={**ALICE, "Idempotency-Key": key, "Content-Type": "application/json"},
                                 content=json.dumps({"seats": 2, "category_id": "cat-jazz-std"}).encode())
        check(reordered.status_code == 201 and reordered.json() == first.json() and reordered.headers.get("idempotent-replayed") == "true",
              "O2.2 the fingerprint does not depend on the order of JSON fields", reordered)
        spaced = await c.post("/v1/holds", headers={**ALICE, "Idempotency-Key": key, "Content-Type": "application/json"},
                              content=b'{ "category_id" : "cat-jazz-std" ,\n "seats" : 2 }')
        check(spaced.status_code == 201 and spaced.json() == first.json(), "whitespace in the body does not change the fingerprint", spaced)

        other_seats = await post_hold(c, ALICE, body("cat-jazz-std", 3), key)
        check(is_problem(other_seats, 422, "idempotency-key-reused"), "O2.2 same key, different body -> 422", other_seats)
        other_category = await post_hold(c, ALICE, body("cat-jazz-vip", 2), key)
        check(is_problem(other_category, 422, "idempotency-key-reused"), "same key, other category -> 422", other_category)
        check(await available(c, "cat-jazz-std") == before - 2, "a rejected reuse changes nothing")

        mine = await post_hold(c, BOB, body("cat-jazz-std", 2), key)
        check(mine.status_code == 201 and mine.json()["id"] != first.json()["id"] and "idempotent-replayed" not in mine.headers,
              "keys are per user: Bob may use the same key string", mine)

        if len(BASES) > 1:
            async with httpx.AsyncClient(base_url=BASES[1], timeout=15) as c2:
                via_other = await post_hold(c2, ALICE, body("cat-jazz-std", 2), key)
                check(via_other.status_code == 201 and via_other.json() == first.json() and via_other.headers.get("idempotent-replayed") == "true",
                      "O2.3 the repeat through another instance returns the stored answer", via_other)

        failed_key = new_key()
        r1 = await post_hold(c, ALICE, body("cat-scarce", 6), failed_key)
        r2 = await post_hold(c, ALICE, body("cat-scarce", 6), failed_key)
        check(is_problem(r1, 409) and is_problem(r2, 409) and "idempotent-replayed" not in r2.headers,
              "a failed attempt (409) is not stored: the repeat is evaluated again", r2)

        before = await available(c, "cat-jazz-std")
        shared = new_key()

        async def parallel(i: int) -> httpx.Response:
            async with httpx.AsyncClient(base_url=BASES[i % len(BASES)], timeout=15) as cc:
                return await post_hold(cc, ALICE, body("cat-jazz-std"), shared)

        replies = await asyncio.gather(*(parallel(i) for i in range(20)))
        codes = sorted(r.status_code for r in replies)
        created = [r for r in replies if r.status_code == 201]
        busy = [r for r in replies if r.status_code == 409 and is_problem(r, 409, "request-in-progress")]
        check(len(created) + len(busy) == 20 and len({r.json()["id"] for r in created}) == 1,
              f"O2.2 20 parallel requests with one key: one hold, statuses {codes}")
        check(all(r.headers.get("retry-after") for r in busy), "409 request-in-progress carries Retry-After")
        check(await available(c, "cat-jazz-std") == before - 1, "20 parallel requests with one key took exactly one seat")
        late = await post_hold(c, ALICE, body("cat-jazz-std"), shared)
        check(late.status_code == 201 and late.headers.get("idempotent-replayed") == "true" and late.json()["id"] == created[0].json()["id"],
              "after they finish, the key answers with the stored result", late)

        if DATABASE_URL:
            expiring = new_key()
            one = await post_hold(c, ALICE, body("cat-jazz-std"), expiring)
            db_query("UPDATE idempotency_keys SET expires_at = now() - interval '1 second' WHERE user_id = 'usr-alice' AND key = %s", (expiring,))
            two = await post_hold(c, ALICE, body("cat-jazz-std"), expiring)
            check(two.status_code == 201 and two.json()["id"] != one.json()["id"] and "idempotent-replayed" not in two.headers,
                  "an expired key is not replayed: the request is a new one", two)
            stored = db_query("SELECT expires_at > now() AS live, state FROM idempotency_keys WHERE user_id = 'usr-alice' AND key = %s", (expiring,))
            check(len(stored) == 1 and stored[0][0] is True and stored[0][1] == "completed", "the expired row was replaced by a live one")
            if os.environ.get("CHECK_PURGE") == "1":
                db_query("INSERT INTO idempotency_keys (user_id, key, operation, fingerprint, status_code, response_body, expires_at) "
                         "SELECT 'usr-alice', 'purge-' || g, 'POST /v1/holds', 'x', 201, '{}', now() - interval '1 hour' FROM generate_series(1, 1200) g")
                deadline = time.time() + float(os.environ.get("PURGE_WAIT_S", "90"))
                left = 1200
                while time.time() < deadline and left:
                    left = db_query("SELECT count(*) FROM idempotency_keys WHERE left(key, 6) = 'purge-'")[0][0]
                    await asyncio.sleep(1)
                check(left == 0, "expired keys are removed in batches by the background job")
        else:
            print("skip DATABASE_URL is not set: expired-key checks need the database")


async def race() -> None:
    category = "cat-race-50"
    async with httpx.AsyncClient(base_url=BASES[0], timeout=15) as c:
        capacity = (await available(c, category))
    stats = {"retries": 0, "transport_errors": 0}
    started = time.time()
    codes = await asyncio.gather(*(buy_with_retries(BASES[i % len(BASES)], USERS[i % len(USERS)], category, stats) for i in range(BUYERS)))
    took = time.time() - started
    won, lost = codes.count(201), codes.count(409)
    async with httpx.AsyncClient(base_url=BASES[0], timeout=15) as c:
        left = await available(c, category)
    if DATABASE_URL:
        sold = db_query("SELECT COALESCE(sum(seats), 0) FROM bookings WHERE category_id = %s AND status IN ('held', 'confirmed')", (category,))[0][0]
    else:
        sold = 0
        async with httpx.AsyncClient(base_url=BASES[0], timeout=30) as c:
            for user in USERS:
                cursor = None
                while True:
                    reply = await c.get("/v1/holds", headers=user, params={"limit": 50, **({"cursor": cursor} if cursor else {})})
                    page = reply.json()
                    sold += sum(h["seats"] for h in page["items"] if h["category_id"] == category)
                    cursor = page["next_cursor"]
                    if not cursor:
                        break
    print(f"     {BUYERS} buyers, {capacity} seats, {took:.1f}s, instances={len(BASES)}, retries={stats['retries']}, transport_errors={stats['transport_errors']}")
    check(won == capacity and lost == BUYERS - capacity and 0 not in codes, f"O2.1 {BUYERS} buyers on {capacity} seats: {won}x201, {lost}x409")
    check(left == 0, f"O2.1 available is exactly 0, not negative (is {left})")
    check(sold == capacity, f"O2.1 the seats of all created holds add up to the capacity (sold {sold} of {capacity})")


async def fault() -> None:
    async with httpx.AsyncClient(base_url=BASES[0], timeout=20) as c:
        before = await available(c, "cat-jazz-std")
        key = new_key()
        died = False
        try:
            reply = await post_hold(c, ALICE, body("cat-jazz-std", 1), key)
            died = reply.status_code in (502, 503, 504)
            check(died, "the armed fault must cut the answer off, but a normal answer arrived", reply)
        except httpx.TransportError as exc:
            died = True
            print(f"ok   no answer: {type(exc).__name__} (the process died after the commit)")
    check(died, "O2.3 the first attempt got no answer")
    async with httpx.AsyncClient(base_url=BASES[-1], timeout=20) as other:
        repeat = await post_hold(other, ALICE, body("cat-jazz-std", 1), key)
        check(repeat.status_code == 201 and repeat.headers.get("idempotent-replayed") == "true",
              "O2.3 the repeat through the other instance returns the stored result", repeat)
        check(await available(other, "cat-jazz-std") == before - 1, "O2.3 the effect is one: one seat taken")
        got = await other.get(repeat.headers["location"], headers=ALICE)
        check(got.status_code == 200 and got.json()["id"] == repeat.json()["id"], "the hold from the stored answer exists", got)
    deadline = time.time() + 60
    async with httpx.AsyncClient(base_url=BASES[0], timeout=5) as first:
        while time.time() < deadline:
            try:
                if (await first.get("/health")).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        else:
            check(False, "the killed instance came back within 60 s")
        again = await post_hold(first, ALICE, body("cat-jazz-std", 1), key)
        check(again.status_code == 201 and again.json()["id"] == repeat.json()["id"] and again.headers.get("idempotent-replayed") == "true",
              "O2.3 the restarted instance gives the same answer, still one effect", again)
        check(await available(first, "cat-jazz-std") == before - 1, "still exactly one seat taken after the restart")


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "functional"):
        await functional()
    if mode in ("all", "race"):
        await race()
    if mode == "fault":
        await fault()
    print(f"\n{passed} checks passed against {', '.join(BASES)}")


asyncio.run(main())
