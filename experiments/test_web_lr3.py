import asyncio
import os
import uuid

import httpx

BASES = os.environ.get("BASES", os.environ.get("BASE", "http://localhost:8080")).split(",")
CLIENT_ORIGIN = os.environ.get("CLIENT_ORIGIN", "http://localhost:8081")
EVIL_ORIGIN = os.environ.get("EVIL_ORIGIN", "http://localhost:8082")
DATABASE_URL = os.environ.get("DATABASE_URL")
PROBLEM = "application/problem+json"
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


def db_query(sql: str, params: tuple = ()) -> list:
    import psycopg

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


def cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"session={token}"}


def hold_headers(token: str, **extra: str) -> dict[str, str]:
    return {**cookie(token), "Idempotency-Key": uuid.uuid4().hex, **extra}


async def login(c: httpx.AsyncClient, who: str, password: str) -> tuple[str, httpx.Response]:
    reply = await c.post("/v1/auth/login", json={"login": who, "password": password})
    c.cookies.clear()
    return reply.cookies.get("session", ""), reply


async def available(c: httpx.AsyncClient, token: str, category: str) -> int:
    reply = await c.get("/v1/events/scr-jazz-1/categories", headers=cookie(token))
    return {x["id"]: x for x in reply.json()["items"]}[category]["available"]


async def main() -> None:
    async with (
        httpx.AsyncClient(base_url=BASES[0], timeout=15) as c,
        httpx.AsyncClient(base_url=BASES[-1], timeout=15) as other,
    ):
        alice, r = await login(c, "alice@example.invalid", "alice-pass")
        check(r.status_code == 200 and r.json() == {"id": "usr-alice", "name": "Аліса Коваль", "email": "alice@example.invalid", "role": "user"},
              "O3.1 login -> 200 with the person, no token in the body", r)
        header = r.headers["set-cookie"].lower()
        check("httponly" in header and "samesite=lax" in header and "path=/" in header and "max-age=" in header,
              "the session cookie is HttpOnly, SameSite=Lax, Path=/, with Max-Age")
        check(alice not in r.text and r.headers.get("cache-control") == "no-store", "the token is only in the cookie; the answer is not cached")
        bob, _ = await login(c, "bob@example.invalid", "bob-pass")
        staff, r = await login(c, "STAFF@example.invalid", "staff-pass")
        check(r.status_code == 200 and r.json()["role"] == "staff", "login is case-insensitive for the e-mail; staff has role staff", r)

        wrong, r1 = await login(c, "alice@example.invalid", "wrong")
        _, r2 = await login(c, "nobody@example.invalid", "wrong")
        check(is_problem(r1, 401, "invalid-credentials") and is_problem(r2, 401, "invalid-credentials") and not wrong,
              "wrong password and unknown login give 401", r1)
        check({k: v for k, v in r1.json().items() if k != "instance"} == {k: v for k, v in r2.json().items() if k != "instance"},
              "the two failures look the same: no user enumeration")
        for payload in ({"login": "alice@example.invalid"}, {"login": "alice@example.invalid", "password": "alice-pass", "role": "staff"},
                        {"login": 1, "password": "x"}):
            r = await c.post("/v1/auth/login", json=payload)
            check(is_problem(r, 422), f"login with a wrong body {list(payload)} -> 422", r)
        r = await c.post("/v1/auth/login", content=b'{"login": ', headers={"Content-Type": "application/json"})
        check(is_problem(r, 400), "login with broken JSON -> 400", r)

        r = await c.get("/v1/me", headers=cookie(alice))
        check(r.status_code == 200 and r.json()["id"] == "usr-alice" and r.json()["role"] == "user", "GET /v1/me returns the person and the role", r)
        check(is_problem(await c.get("/v1/me"), 401), "GET /v1/me without a session -> 401")
        check(is_problem(await c.get("/v1/me", headers=cookie("garbage")), 401), "an invented session value -> 401")
        r = await c.get("/v1/me", headers={"X-User-Id": "usr-alice"})
        check(is_problem(r, 401), "O3.1 X-User-Id alone is not accepted any more", r)
        r = await c.get("/v1/me", headers={**cookie(alice), "X-User-Id": "usr-bob"})
        check(r.json()["id"] == "usr-alice", "X-User-Id cannot override the session", r)
        check(is_problem(await c.post("/v1/holds", headers={"X-User-Id": "usr-alice", "Idempotency-Key": uuid.uuid4().hex},
                                      json={"category_id": "cat-jazz-std", "seats": 1}), 401), "creating a hold by X-User-Id -> 401")

        r = await other.get("/v1/me", headers=cookie(alice))
        check(r.status_code == 200 and r.json()["id"] == "usr-alice", "O3.1 a session from one instance works on the other", r)
        r = await other.post("/v1/auth/logout", headers=cookie(alice))
        check(r.status_code == 204 and "max-age=0" in r.headers["set-cookie"].lower(), "logout through the other instance -> 204 and the cookie is cleared", r)
        r = await c.get("/v1/me", headers=cookie(alice))
        check(is_problem(r, 401), "O3.1 after logout the old cookie is rejected: the session is deleted on the server", r)
        check(is_problem(await c.post("/v1/auth/logout", headers=cookie(alice)), 401), "logout without a live session -> 401")
        alice, _ = await login(c, "alice@example.invalid", "alice-pass")

        if DATABASE_URL:
            db_query("UPDATE sessions SET expires_at = now() - interval '1 second' WHERE token_hash = encode(sha256(convert_to(%s, 'UTF8')), 'hex')", (bob,))
            r = await c.get("/v1/me", headers=cookie(bob))
            check(is_problem(r, 401), "O3.1 an expired session is rejected", r)
            bob, _ = await login(c, "bob@example.invalid", "bob-pass")
            stored = db_query("SELECT password_hash FROM users WHERE id = 'usr-alice'")[0][0]
            check(stored.startswith("scrypt$") and "alice-pass" not in stored, "O3.1 the password is stored as a salted scrypt hash")
            tokens = db_query("SELECT count(*) FROM sessions WHERE token_hash = %s", (alice,))[0][0]
            check(tokens == 0, "the session token itself is not stored, only its hash")
        else:
            print("skip DATABASE_URL is not set: expiry and storage checks need the database")

        r = await c.post("/v1/holds", headers=hold_headers(alice), json={"category_id": "cat-jazz-std", "seats": 1})
        mine = r.json()
        check(r.status_code == 201, "a signed-in user creates a hold", r)
        r = await c.get(f"/v1/holds/{mine['id']}", headers=cookie(bob))
        missing = await c.get("/v1/holds/no-such-hold", headers=cookie(bob))
        check(is_problem(r, 404) and is_problem(missing, 404) and r.json()["title"] == missing.json()["title"],
              "O3.2 someone else's hold -> 404, the same as a missing one", r)
        r = await c.patch(f"/v1/holds/{mine['id']}", headers=cookie(bob), json={"holder_name": "Hacker"})
        check(is_problem(r, 404), "O3.2 changing someone else's hold -> 404", r)
        r = await c.patch("/v1/holds/no-such-hold", headers=cookie(alice), json={"holder_name": "X"})
        check(is_problem(r, 404), "changing a missing hold -> 404", r)
        listed = (await c.get("/v1/holds", headers=cookie(bob), params={"limit": 50})).json()["items"]
        check(all(h["id"] != mine["id"] for h in listed), "the list shows only my own holds")

        r = await c.patch(f"/v1/holds/{mine['id']}", headers=cookie(alice), json={"holder_name": "Нове Імʼя"})
        check(r.status_code == 200 and r.json()["holder_name"] == "Нове Імʼя" and r.json()["version"] == mine["version"] + 1
              and r.headers["etag"] == f'"{mine["version"] + 1}"', "O3.2 the owner changes the name; version grows", r)
        for forbidden in ({"user_id": "usr-bob"}, {"status": "confirmed"}, {"version": 99}, {"seats": 5}, {"category_id": "cat-jazz-vip"},
                          {"holder_name": "A", "version": 99}, {}, {"holder_name": 5}, {"holder_name": ""}):
            r = await c.patch(f"/v1/holds/{mine['id']}", headers=cookie(alice), json=forbidden)
            check(is_problem(r, 422), f"O3.2 PATCH {forbidden} -> 422", r)
        after = (await c.get(f"/v1/holds/{mine['id']}", headers=cookie(alice))).json()
        check(after["status"] == "held" and after["seats"] == 1 and after["version"] == mine["version"] + 1 and after["holder_name"] == "Нове Імʼя",
              "rejected changes left the hold untouched")

        categories = "/v1/categories/cat-jazz-std"
        check(is_problem(await c.post(f"{categories}/close-sales"), 401), "O3.2 staff function without a session -> 401")
        r = await c.post(f"{categories}/close-sales", headers=cookie(alice))
        check(is_problem(r, 403, "forbidden"), "O3.2 staff function for a user -> 403", r)
        check(is_problem(await c.post("/v1/categories/no-such/close-sales", headers=cookie(alice)), 403), "403 comes before 404 for a user")
        r = await c.post(f"{categories}/close-sales", headers=cookie(staff))
        check(r.status_code == 200 and r.json()["sales_open"] is False and r.json()["id"] == "cat-jazz-std", "staff closes the sales of a category", r)
        r = await c.post("/v1/holds", headers=hold_headers(alice), json={"category_id": "cat-jazz-std", "seats": 1})
        check(is_problem(r, 409, "sales-closed"), "a hold in a closed category -> 409 sales-closed", r)
        check(is_problem(await c.post("/v1/categories/no-such/close-sales", headers=cookie(staff)), 404), "staff on a missing category -> 404")
        r = await c.post(f"{categories}/open-sales", headers=cookie(staff))
        check(r.status_code == 200 and r.json()["sales_open"] is True, "staff opens the sales again", r)
        r = await c.post("/v1/holds", headers=hold_headers(alice), json={"category_id": "cat-jazz-std", "seats": 1})
        check(r.status_code == 201, "sales are open again: a hold is created", r)

        before = await available(c, alice, "cat-jazz-std")
        body = {"category_id": "cat-jazz-std", "seats": 1}
        for label, extra in (
            ("Origin of a foreign site", {"Origin": EVIL_ORIGIN, "Sec-Fetch-Site": "same-site"}),
            ("Origin of a foreign site, cross-site", {"Origin": EVIL_ORIGIN, "Sec-Fetch-Site": "cross-site"}),
            ("Origin null", {"Origin": "null"}),
            ("Sec-Fetch-Site cross-site without Origin", {"Sec-Fetch-Site": "cross-site"}),
            ("Sec-Fetch-Site same-site without Origin", {"Sec-Fetch-Site": "same-site"}),
            ("foreign Origin without Sec-Fetch-Site", {"Origin": EVIL_ORIGIN}),
        ):
            r = await c.post("/v1/holds", headers=hold_headers(alice, **extra), json=body)
            check(is_problem(r, 403, "csrf-rejected"), f"O3.3 POST from {label} -> 403", r)
        r = await c.patch(f"/v1/holds/{mine['id']}", headers={**cookie(alice), "Origin": EVIL_ORIGIN, "Sec-Fetch-Site": "same-site"}, json={"holder_name": "Evil"})
        check(is_problem(r, 403, "csrf-rejected"), "O3.3 PATCH from a foreign site -> 403", r)
        r = await c.post("/v1/categories/cat-jazz-std/close-sales", headers={**cookie(staff), "Origin": EVIL_ORIGIN, "Sec-Fetch-Site": "same-site"})
        check(is_problem(r, 403, "csrf-rejected"), "O3.3 staff action from a foreign site -> 403", r)
        r = await c.post("/v1/auth/login", json={"login": "alice@example.invalid", "password": "alice-pass"},
                         headers={"Origin": EVIL_ORIGIN, "Sec-Fetch-Site": "same-site"})
        check(is_problem(r, 403, "csrf-rejected") and "set-cookie" not in r.headers, "O3.3 login from a foreign site -> 403, no cookie", r)
        check(await available(c, alice, "cat-jazz-std") == before, "O3.3 the refused requests had no effect: seats unchanged")
        name = (await c.get(f"/v1/holds/{mine['id']}", headers=cookie(alice))).json()["holder_name"]
        check(name == "Нове Імʼя", "O3.3 the name was not changed by the foreign site")
        sc = (await c.get("/v1/events/scr-jazz-1/categories", headers=cookie(alice))).json()["items"]
        check({x["id"]: x for x in sc}["cat-jazz-std"]["sales_open"] is True, "O3.3 the sales were not closed by the foreign site")

        for label, extra in (
            ("the client origin", {"Origin": CLIENT_ORIGIN, "Sec-Fetch-Site": "same-site"}),
            ("the client origin, cross-site", {"Origin": CLIENT_ORIGIN, "Sec-Fetch-Site": "cross-site"}),
            ("a non-browser client", {}),
            ("same-origin", {"Sec-Fetch-Site": "same-origin"}),
        ):
            r = await c.post("/v1/holds", headers=hold_headers(alice, **extra), json=body)
            check(r.status_code == 201, f"O3.3 POST from {label} is accepted", r)
        check(await available(c, alice, "cat-jazz-std") == before - 4, "the accepted requests took their seats")

        r = await c.options("/v1/holds", headers={"Origin": CLIENT_ORIGIN, "Access-Control-Request-Method": "POST",
                                                  "Access-Control-Request-Headers": "content-type,idempotency-key"})
        allow_headers = r.headers.get("access-control-allow-headers", "").lower()
        check(r.status_code == 200 and r.headers.get("access-control-allow-origin") == CLIENT_ORIGIN
              and r.headers.get("access-control-allow-credentials") == "true" and "idempotency-key" in allow_headers,
              "O3.3 preflight from the client origin: exact origin, credentials, Idempotency-Key", r)
        check("*" not in (r.headers.get("access-control-allow-origin", ""), allow_headers) and "x-user-id" not in allow_headers,
              "no wildcard in the allowed origin and headers; X-User-Id is gone")
        r = await c.options("/v1/holds", headers={"Origin": EVIL_ORIGIN, "Access-Control-Request-Method": "POST"})
        check("access-control-allow-origin" not in r.headers, "O3.3 preflight from a foreign origin gets no permission", r)
        r = await c.options("/v1/holds", headers={"Origin": CLIENT_ORIGIN, "Access-Control-Request-Method": "DELETE"})
        check(r.status_code == 400, "a method that the API does not use is not allowed in preflight", r)
        r = await c.get("/v1/me", headers={**cookie(alice), "Origin": EVIL_ORIGIN})
        check("access-control-allow-origin" not in r.headers, "O3.3 a foreign site cannot read the answer: no Access-Control-Allow-Origin", r)
        r = await c.get("/v1/me", headers={**cookie(alice), "Origin": CLIENT_ORIGIN})
        check(r.headers.get("access-control-allow-origin") == CLIENT_ORIGIN and r.headers.get("access-control-allow-credentials") == "true",
              "the client origin can read the answer", r)
        check(bool(r.headers.get("x-request-id")), "X-Request-ID is on CORS answers")

    print(f"\n{passed} checks passed against {', '.join(BASES)}")


asyncio.run(main())
