import argparse
import asyncio
import sys

from . import db, seats
from .jsonlog import log

SEATS_PER_ROW = 10

_INSERT_SEATS = """
    INSERT INTO seats (id, screening_id, category_id, row_label, seat_number)
    SELECT c.id || ':' || r.label || (mod(g, %(per_row)s) + 1), c.screening_id, c.id,
           c.name || ' ' || r.label, mod(g, %(per_row)s) + 1
    FROM seat_categories c
    CROSS JOIN generate_series(%(first)s::int, %(last)s::int) AS g
    CROSS JOIN LATERAL (
        SELECT CASE WHEN g / %(per_row)s < 26 THEN chr(65 + g / %(per_row)s) ELSE 'R' || (g / %(per_row)s + 1) END AS label
    ) r
    WHERE c.id = %(category)s
    ON CONFLICT DO NOTHING
"""


async def backfill(batch: int) -> None:
    await db.open_pool()
    try:
        async with db.connection() as conn:
            cur = await conn.execute("SELECT id, capacity FROM seat_categories ORDER BY id")
            categories = await cur.fetchall()
        for category in categories:
            created = 0
            for first in range(0, category["capacity"], batch):
                last = min(first + batch, category["capacity"]) - 1
                async with db.connection() as conn, conn.transaction():
                    cur = await conn.execute(
                        _INSERT_SEATS,
                        {"per_row": SEATS_PER_ROW, "first": first, "last": last, "category": category["id"]},
                    )
                    created += cur.rowcount
            log("seats.backfill_category", category_id=category["id"], created=created)
        assigned = 0
        failed = 0
        async with db.connection() as conn:
            cur = await conn.execute(
                """
                SELECT b.id, b.category_id, b.seats FROM bookings b
                WHERE b.status IN ('held', 'confirmed')
                  AND NOT EXISTS (SELECT 1 FROM booking_seats bs WHERE bs.booking_id = b.id)
                ORDER BY b.created_at, b.id
                """
            )
            pending = await cur.fetchall()
        for booking in pending:
            async with db.connection() as conn, conn.transaction():
                done = await seats.assign_automatically(conn, booking["id"], booking["category_id"], booking["seats"])
            assigned += bool(done)
            failed += not done
        log("seats.backfill_done", bookings_assigned=assigned, bookings_failed=failed)
        print(f"seats created per category: see log; bookings assigned: {assigned}, not assigned: {failed}")
    finally:
        await db.close_pool()


_CHECKS = [
    (
        "every category has exactly capacity seats",
        """
        SELECT c.id FROM seat_categories c
        WHERE (SELECT count(*) FROM seats s WHERE s.category_id = c.id) <> c.capacity
        """,
    ),
    (
        "occupied seats = capacity - available",
        """
        SELECT c.id FROM seat_categories c
        WHERE (SELECT count(*) FROM booking_seats bs JOIN seats s ON s.id = bs.seat_id WHERE s.category_id = c.id)
              <> c.capacity - c.available
        """,
    ),
    (
        "active bookings hold exactly their number of seats",
        """
        SELECT b.id FROM bookings b
        WHERE b.status IN ('held', 'confirmed')
          AND (SELECT count(*) FROM booking_seats bs WHERE bs.booking_id = b.id) <> b.seats
        """,
    ),
    (
        "finished bookings hold no seats",
        """
        SELECT b.id FROM bookings b
        WHERE b.status IN ('expired', 'cancelled', 'refunded')
          AND EXISTS (SELECT 1 FROM booking_seats bs WHERE bs.booking_id = b.id)
        """,
    ),
    (
        "booked seats belong to the category of their booking",
        """
        SELECT bs.seat_id FROM booking_seats bs
        JOIN seats s ON s.id = bs.seat_id JOIN bookings b ON b.id = bs.booking_id
        WHERE s.category_id <> b.category_id
        """,
    ),
]


async def check() -> int:
    await db.open_pool()
    failed = 0
    try:
        async with db.connection() as conn:
            for title, sql in _CHECKS:
                cur = await conn.execute(sql)
                bad = [next(iter(r.values())) for r in await cur.fetchall()]
                if bad:
                    failed += 1
                    print(f"FAIL {title}: {', '.join(map(str, bad[:10]))}")
                else:
                    print(f"ok   {title}")
    finally:
        await db.close_pool()
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.seats_admin")
    sub = parser.add_subparsers(dest="command", required=True)
    fill = sub.add_parser("backfill")
    fill.add_argument("--batch", type=int, default=100)
    sub.add_parser("check")
    args = parser.parse_args()
    if args.command == "backfill":
        asyncio.run(backfill(args.batch))
    else:
        sys.exit(asyncio.run(check()))


if __name__ == "__main__":
    main()
