import asyncio
import os
import pathlib
import time
import uuid

import httpx

BASES = os.environ.get("BASES", os.environ.get("BASE", "http://localhost:8080")).split(",")
DATABASE_URL = os.environ["DATABASE_URL"]
RESET = pathlib.Path(__file__).with_name("web_lr2_reset.sql")
RACE = "cat-race-50"
passed = 0


def check(condition: bool, what: str, reply: httpx.Response | None = None) -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAIL {what}" + (f": {reply.status_code} {reply.text}" if reply is not None else ""))
    passed += 1
    print(f"ok   {what}")


def is_problem(reply: httpx.Response, status: int, slug: str | None = None) -> bool:
    if not reply.headers.get("content-type", "").startswith("application/problem+json"):
        return False
    body = reply.json()
    return reply.status_code == status and (slug is None or body["type"].endswith(slug))


def sql(text: str, params: tuple = ()) -> list:
    import psycopg

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        cur = conn.execute(text, params) if params else conn.execute(text)
        return cur.fetchall() if cur.description else []


def set_flag(enabled: bool) -> None:
    sql("UPDATE feature_flags SET enabled = %s, updated_at = now() WHERE name = 'explicit-seats'", (enabled,))


def cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"session={token}"}


def keyed(token: str) -> dict[str, str]:
    return {**cookie(token), "Idempotency-Key": uuid.uuid4().hex}


async def login(c: httpx.AsyncClient, who: str, password: str) -> str:
    reply = await c.post("/v1/auth/login", json={"login": who, "password": password})
    c.cookies.clear()
    return reply.cookies.get("session", "")


def available(category: str) -> int:
    return sql("SELECT available FROM seat_categories WHERE id = %s", (category,))[0][0]


def seats_of(booking: str) -> list[tuple[str, int]]:
    return sql(
        "SELECT s.row_label, s.seat_number FROM booking_seats bs JOIN seats s ON s.id = bs.seat_id "
        "WHERE bs.booking_id = %s ORDER BY s.seat_number",
        (booking,),
    )


def booked_total() -> int:
    return sql("SELECT count(*) FROM booking_seats")[0][0]


def consistent() -> bool:
    bad = sql(
        """
        SELECT c.id FROM seat_categories c
        WHERE (SELECT count(*) FROM seats s WHERE s.category_id = c.id) <> c.capacity
           OR (SELECT count(*) FROM booking_seats bs JOIN seats s ON s.id = bs.seat_id WHERE s.category_id = c.id)
              <> c.capacity - c.available
        """
    )
    bad += sql(
        """
        SELECT b.id FROM bookings b
        WHERE (b.status IN ('held', 'confirmed') AND (SELECT count(*) FROM booking_seats bs WHERE bs.booking_id = b.id) <> b.seats)
           OR (b.status IN ('expired', 'cancelled', 'refunded') AND EXISTS (SELECT 1 FROM booking_seats bs WHERE bs.booking_id = b.id))
        """
    )
    return not bad


async def main() -> None:
    sql(RESET.read_text())
    set_flag(False)
    async with (
        httpx.AsyncClient(base_url=BASES[0], timeout=20) as c,
        httpx.AsyncClient(base_url=BASES[-1], timeout=20) as other,
    ):
        alice = await login(c, "alice@example.invalid", "alice-pass")
        bob = await login(c, "bob@example.invalid", "bob-pass")
        check(bool(alice and bob), "both users are logged in")
        have = sql("SELECT count(*) FROM seats WHERE category_id = %s", (RACE,))[0][0]
        check(have == 50, "the seats are backfilled (50 seats in the race category); run seats_admin backfill if not")
        check(consistent(), "before the test: seats, bookings and available agree (seats_admin check)")

        r = await c.get("/v1/features", headers=cookie(alice))
        check(r.status_code == 200 and r.json() == {"explicit_seats": False}, "O6.1 the flag is off: /v1/features says so", r)

        before = available(RACE)
        key = uuid.uuid4().hex
        old_body = {"category_id": RACE, "seats": 2}
        r = await c.post("/v1/holds", headers={**cookie(alice), "Idempotency-Key": key}, json=old_body)
        check(r.status_code == 201 and "places" not in r.json() and r.json()["seats"] == 2,
              "O6.1 flag off: the old client request works and the answer has no new field", r)
        first = r.json()["id"]
        placed = seats_of(first)
        check(len(placed) == 2 and placed[0][0] == placed[1][0] and placed[1][1] == placed[0][1] + 1,
              "O6.1 flag off: the server assigned two adjacent seats of one row on its own")
        check(available(RACE) == before - 2, "the count of the category went down by 2 as before")
        r2 = await c.post("/v1/holds", headers={**cookie(alice), "Idempotency-Key": key}, json=old_body)
        check(r2.status_code == 201 and r2.headers.get("idempotent-replayed") == "true" and r2.json()["id"] == first,
              "O6.1 the old request with the same key is a replay: its fingerprint did not change", r2)

        r = await c.get(f"/v1/categories/{RACE}/seats", headers=cookie(alice))
        check(is_problem(r, 404, "feature-disabled"), "flag off: the seat map is not available", r)
        r = await c.post("/v1/holds", headers=keyed(alice), json={"category_id": RACE, "seat_ids": [f"{RACE}:E1"]})
        check(is_problem(r, 422, "seat-selection-disabled") and available(RACE) == before - 2,
              "flag off: choosing seats is refused and nothing changes", r)

        set_flag(True)
        r = await c.get("/v1/features", headers=cookie(alice))
        check(r.json() == {"explicit_seats": True}, "O6.1 flag on: /v1/features says so", r)
        r = await c.get(f"/v1/categories/{RACE}/seats", headers=cookie(alice))
        items = r.json()["items"]
        taken_now = {i["id"] for i in items if not i["free"]}
        check(r.status_code == 200 and len(items) == 50 and len(taken_now) == 2, "flag on: the seat map has 50 seats, 2 are taken", r)
        r = await c.get("/v1/categories/no-such/seats", headers=cookie(alice))
        check(is_problem(r, 404, "not-found"), "the seat map of an unknown category -> 404", r)
        r = await c.get(f"/v1/holds/{first}", headers=cookie(alice))
        check([p["id"] for p in r.json()["places"]] == sorted(
            [i["id"] for i in items if i["id"] in taken_now], key=lambda s: int(s.split(":")[1][1:])),
              "flag on: an old hold shows the seats that were assigned while the flag was off", r)

        before = available(RACE)
        r = await c.post("/v1/holds", headers=keyed(alice), json={"category_id": RACE, "seats": 3})
        auto = r.json()
        check(r.status_code == 201 and len(auto["places"]) == 3 and len({p["row"] for p in auto["places"]}) == 1,
              "O6.1 flag on: the old request gets 3 seats in one row, with the places in the answer", r)
        check(not ({p["id"] for p in auto["places"]} & taken_now), "the assigned seats were free")

        free_ids = [i["id"] for i in items if i["free"] and i["id"] not in {p["id"] for p in auto["places"]}]
        chosen = free_ids[-2:]
        before = available(RACE)
        r = await c.post("/v1/holds", headers=keyed(alice), json={"category_id": RACE, "seat_ids": chosen})
        mine = r.json()
        check(r.status_code == 201 and mine["seats"] == 2 and {p["id"] for p in mine["places"]} == set(chosen),
              "O6.1 the new client gets exactly the chosen seats", r)
        check(available(RACE) == before - 2, "the chosen seats reduced available by 2")
        r = await c.get("/v1/holds?limit=50", headers=cookie(alice))
        check(all("places" in h for h in r.json()["items"]), "the list of holds carries places", r)
        r = await c.patch(f"/v1/holds/{mine['id']}", headers=cookie(alice), json={"holder_name": "Нове ім'я"})
        check(r.status_code == 200 and len(r.json()["places"]) == 2, "PATCH keeps the places in the answer", r)

        before, total = available(RACE), booked_total()
        r = await c.post("/v1/holds", headers=keyed(bob), json={"category_id": RACE, "seat_ids": [chosen[0]]})
        check(is_problem(r, 409, "seat-taken") and available(RACE) == before and booked_total() == total,
              "O6.1 a taken seat -> 409 seat-taken; available and the seats are unchanged (the transaction was rolled back)", r)
        r = await c.post("/v1/holds", headers=keyed(bob), json={"category_id": RACE, "seat_ids": [free_ids[0], chosen[1]]})
        check(is_problem(r, 409, "seat-taken") and booked_total() == total and available(RACE) == before,
              "one taken seat among free ones: nothing is booked", r)
        for label, payload, slug in (
            ("duplicate seat ids", {"category_id": RACE, "seat_ids": [free_ids[0], free_ids[0]]}, None),
            ("an unknown seat", {"category_id": RACE, "seat_ids": ["cat-race-50:Z99"]}, "invalid-seat"),
            ("a seat of another category", {"category_id": RACE, "seat_ids": ["cat-scarce:A1"]}, "invalid-seat"),
            ("both seats and seat_ids", {"category_id": RACE, "seats": 1, "seat_ids": [free_ids[0]]}, None),
            ("neither seats nor seat_ids", {"category_id": RACE}, None),
            ("an empty seat_ids", {"category_id": RACE, "seat_ids": []}, None),
        ):
            r = await c.post("/v1/holds", headers=keyed(bob), json=payload)
            check(is_problem(r, 422, slug) and available(RACE) == before and booked_total() == total,
                  f"{label} -> 422, nothing changes", r)

        target = free_ids[5]
        clients = [c, other]
        users = [alice, bob]
        replies = await asyncio.gather(*(
            clients[i % 2].post("/v1/holds", headers=keyed(users[i % 2]), json={"category_id": RACE, "seat_ids": [target]})
            for i in range(30)))
        codes = sorted(r.status_code for r in replies)
        check(codes == [201] + [409] * 29 and all(is_problem(r, 409, "seat-taken") for r in replies if r.status_code == 409),
              "O6.1 30 parallel requests for one seat through two instances: one 201, 29 seat-taken")
        check(consistent(), "after the race the seats, the bookings and available agree")

        sql("UPDATE seat_categories SET sales_open = true WHERE id = 'cat-scarce'")
        replies = await asyncio.gather(*(
            clients[i % 2].post("/v1/holds", headers=keyed(users[i % 2]), json={"category_id": "cat-scarce", "seats": 2})
            for i in range(40)))
        codes = sorted(r.status_code for r in replies)
        check(codes == [201, 201] + [409] * 38, "O6.1 40 parallel old-style requests for 2 seats each in a 5-seat category: 2 succeed")
        check(available("cat-scarce") == 1 and consistent(), "cat-scarce: one seat left and the seats agree with available")

        sql("UPDATE bookings SET created_at = now() - interval '20 minutes', hold_expires_at = now() - interval '1 minute' WHERE id = %s", (mine["id"],))
        deadline = time.time() + 20
        status = "held"
        while time.time() < deadline and status == "held":
            await asyncio.sleep(1)
            status = sql("SELECT status FROM bookings WHERE id = %s", (mine["id"],))[0][0]
        check(status == "expired" and not seats_of(mine["id"]), "O6.1 an expired hold releases its seats (the sweeper and the trigger)")
        r = await c.post("/v1/holds", headers=keyed(bob), json={"category_id": RACE, "seat_ids": chosen})
        check(r.status_code == 201, "the released seats can be chosen again", r)
        sql("UPDATE bookings SET status = 'cancelled' WHERE id = %s", (r.json()["id"],))
        check(not seats_of(r.json()["id"]), "a cancelled booking releases its seats in the database itself (trigger)")
        sql("UPDATE seat_categories SET available = available + 2 WHERE id = %s", (RACE,))
        check(consistent(), "the manual cancellation plus the matching available keeps everything consistent")

        set_flag(False)
        r = await c.get(f"/v1/holds/{auto['id']}", headers=cookie(alice))
        check(r.status_code == 200 and "places" not in r.json(), "O6.1 back to the flag off: the old shape of the hold", r)
        r = await c.post("/v1/holds", headers=keyed(alice), json={"category_id": RACE, "seats": 1})
        check(r.status_code == 201 and "places" not in r.json() and len(seats_of(r.json()["id"])) == 1,
              "flag off again: the old client works and its seat is still recorded")
        check(consistent(), "after the return to flag off the seats stay consistent")

    sql(RESET.read_text())
    print(f"\n{passed} checks passed against {', '.join(BASES)}")


asyncio.run(main())
