from typing import Any

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from . import db
from .auth import current_user
from .problems import Problem

router = APIRouter(tags=["seats"], dependencies=[Depends(current_user)])

FLAG = "explicit-seats"


async def explicit_seats_enabled(conn: AsyncConnection) -> bool:
    cur = await conn.execute("SELECT enabled FROM feature_flags WHERE name = %s", (FLAG,))
    row = await cur.fetchone()
    return bool(row and row["enabled"])


async def assign_automatically(conn: AsyncConnection, booking_id: str, category_id: str, count: int) -> list[str]:
    cur = await conn.execute(
        """
        WITH free AS (
            SELECT s.id, s.row_label, s.seat_number,
                   s.seat_number - row_number() OVER (PARTITION BY s.row_label ORDER BY s.seat_number) AS island
            FROM seats s
            WHERE s.category_id = %(category)s
              AND NOT EXISTS (SELECT 1 FROM booking_seats bs WHERE bs.seat_id = s.id)
        ), run AS (
            SELECT row_label, island FROM free
            GROUP BY row_label, island HAVING count(*) >= %(count)s
            ORDER BY row_label, min(seat_number) LIMIT 1
        ), picked AS (
            SELECT f.id, f.row_label, f.seat_number FROM free f JOIN run r USING (row_label, island)
            ORDER BY f.seat_number LIMIT %(count)s
        ), fallback AS (
            SELECT id, row_label, seat_number FROM free
            WHERE NOT EXISTS (SELECT 1 FROM picked)
            ORDER BY row_label, seat_number LIMIT %(count)s
        )
        SELECT id FROM picked UNION ALL SELECT id FROM fallback
        """,
        {"category": category_id, "count": count},
    )
    ids = [r["id"] for r in await cur.fetchall()]
    if len(ids) != count:
        return []
    await conn.execute(
        "INSERT INTO booking_seats (seat_id, booking_id) SELECT unnest(%s::text[]), %s", (ids, booking_id)
    )
    return ids


async def assign_chosen(conn: AsyncConnection, booking_id: str, category_id: str, seat_ids: list[str]) -> None:
    cur = await conn.execute("SELECT id FROM seats WHERE category_id = %s AND id = ANY(%s)", (category_id, seat_ids))
    known = {r["id"] for r in await cur.fetchall()}
    unknown = [s for s in seat_ids if s not in known]
    if unknown:
        raise Problem(422, "invalid-seat", "Seat does not belong to this category", ", ".join(unknown))
    cur = await conn.execute(
        """
        INSERT INTO booking_seats (seat_id, booking_id)
        SELECT s.id, %s FROM seats s
        WHERE s.id = ANY(%s) AND NOT EXISTS (SELECT 1 FROM booking_seats bs WHERE bs.seat_id = s.id)
        RETURNING seat_id
        """,
        (booking_id, seat_ids),
    )
    taken = len(await cur.fetchall())
    if taken != len(seat_ids):
        raise Problem(409, "seat-taken", "A chosen seat is already taken", "Pick other seats and try again")


async def places_of(conn: AsyncConnection, booking_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not booking_ids:
        return {}
    cur = await conn.execute(
        """
        SELECT bs.booking_id, s.id, s.row_label, s.seat_number
        FROM booking_seats bs JOIN seats s ON s.id = bs.seat_id
        WHERE bs.booking_id = ANY(%s)
        ORDER BY s.row_label, s.seat_number
        """,
        (booking_ids,),
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for r in await cur.fetchall():
        result.setdefault(r["booking_id"], []).append(
            {"id": r["id"], "row": r["row_label"], "number": r["seat_number"]}
        )
    return result


@router.get("/v1/features")
async def features() -> dict[str, bool]:
    async with db.connection() as conn:
        return {"explicit_seats": await explicit_seats_enabled(conn)}


@router.get("/v1/categories/{category_id}/seats")
async def list_seats(category_id: str) -> dict[str, Any]:
    async with db.connection() as conn:
        if not await explicit_seats_enabled(conn):
            raise Problem(404, "feature-disabled", "Seat selection is not enabled")
        cur = await conn.execute("SELECT 1 FROM seat_categories WHERE id = %s", (category_id,))
        if await cur.fetchone() is None:
            raise Problem(404, "not-found", "Category not found")
        cur = await conn.execute(
            """
            SELECT s.id, s.row_label, s.seat_number, bs.seat_id IS NULL AS free
            FROM seats s LEFT JOIN booking_seats bs ON bs.seat_id = s.id
            WHERE s.category_id = %s
            ORDER BY s.row_label, s.seat_number
            """,
            (category_id,),
        )
        rows = await cur.fetchall()
    return {
        "items": [{"id": r["id"], "row": r["row_label"], "number": r["seat_number"], "free": r["free"]} for r in rows]
    }
