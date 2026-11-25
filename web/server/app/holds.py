import asyncio
import uuid
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from . import config, db, idempotency
from .auth import current_user
from .faults import fault
from .formats import decode_cursor, encode_cursor, iso, money
from .jsonlog import log
from .problems import Problem

router = APIRouter(tags=["holds"])

OPERATION = "POST /v1/holds"


class HoldPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    holder_name: str = Field(min_length=1, max_length=100)


class HoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category_id: str = Field(min_length=1, max_length=64)
    seats: int = Field(ge=1, le=config.HOLD_MAX_SEATS)


_HOLD_SELECT = """
    SELECT b.id, b.screening_id, b.category_id, b.seats, b.holder_name, b.status, b.version,
           b.created_at, b.hold_expires_at, c.price_minor, c.currency
    FROM bookings b JOIN seat_categories c ON c.id = b.category_id
"""


def _view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "performance_id": row["screening_id"],
        "category_id": row["category_id"],
        "seats": row["seats"],
        "holder_name": row["holder_name"],
        "status": row["status"],
        "version": row["version"],
        "created_at": iso(row["created_at"]),
        "expires_at": iso(row["hold_expires_at"]),
        "total": money(row["seats"] * row["price_minor"], row["currency"]),
    }


async def _take_seats_unprotected(conn: AsyncConnection, category_id: str, seats: int) -> bool:
    cur = await conn.execute(
        """
        SELECT c.available, c.sales_open
        FROM seat_categories c JOIN screenings s ON s.id = c.screening_id
        WHERE c.id = %s AND s.status = 'scheduled' AND s.starts_at > now()
        """,
        (category_id,),
    )
    row = await cur.fetchone()
    if row is None or not row["sales_open"] or row["available"] < seats:
        return False
    await asyncio.sleep(0)
    await conn.execute(
        "UPDATE seat_categories SET available = %s WHERE id = %s", (row["available"] - seats, category_id)
    )
    return True


async def _take_seats(conn: AsyncConnection, category_id: str, seats: int) -> bool:
    if config.INVARIANT_MODE == "unprotected":
        return await _take_seats_unprotected(conn, category_id, seats)
    cur = await conn.execute(
        """
        UPDATE seat_categories c SET available = c.available - %(seats)s
        FROM screenings s
        WHERE c.id = %(category)s AND s.id = c.screening_id
          AND c.sales_open AND c.available >= %(seats)s
          AND s.status = 'scheduled' AND s.starts_at > now()
        RETURNING c.id
        """,
        {"seats": seats, "category": category_id},
    )
    return await cur.fetchone() is not None


async def expire_due(conn: AsyncConnection, category_id: str) -> int:
    cur = await conn.execute(
        """
        WITH due AS (
            SELECT id FROM bookings
            WHERE category_id = %s AND status = 'held' AND hold_expires_at <= now()
            ORDER BY id FOR UPDATE
        )
        UPDATE bookings b SET status = 'expired', version = b.version + 1
        FROM due WHERE b.id = due.id
        RETURNING b.seats
        """,
        (category_id,),
    )
    freed = sum(row["seats"] for row in await cur.fetchall())
    if freed:
        await conn.execute("UPDATE seat_categories SET available = available + %s WHERE id = %s", (freed, category_id))
    return freed


async def _why_not(conn: AsyncConnection, category_id: str, seats: int) -> Problem:
    cur = await conn.execute(
        """
        SELECT c.sales_open, c.available, s.status, s.starts_at > now() AS upcoming
        FROM seat_categories c JOIN screenings s ON s.id = c.screening_id WHERE c.id = %s
        """,
        (category_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return Problem(404, "not-found", "Category not found")
    if row["status"] != "scheduled" or not row["upcoming"]:
        return Problem(
            409, "performance-unavailable", "Performance is not on sale", "It is cancelled, finished or started"
        )
    if not row["sales_open"]:
        return Problem(409, "sales-closed", "Sales of this category are closed")
    return Problem(409, "not-enough-seats", "Not enough free seats", f"Requested {seats}, available {row['available']}")


async def _create(conn: AsyncConnection, user: dict[str, Any], body: HoldCreate) -> dict[str, Any]:
    taken = await _take_seats(conn, body.category_id, body.seats)
    if not taken and await expire_due(conn, body.category_id):
        taken = await _take_seats(conn, body.category_id, body.seats)
    if not taken:
        raise await _why_not(conn, body.category_id, body.seats)

    hold_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO bookings (id, user_id, screening_id, category_id, seats, holder_name, hold_expires_at)
        SELECT %s, %s, c.screening_id, c.id, %s, %s, now() + make_interval(mins => %s)
        FROM seat_categories c WHERE c.id = %s
        """,
        (hold_id, user["id"], body.seats, user["display_name"], config.HOLD_MINUTES, body.category_id),
    )
    cur = await conn.execute(_HOLD_SELECT + " WHERE b.id = %s", (hold_id,))
    return _view(await cur.fetchone())


@router.post("/v1/holds", status_code=201)
async def create_hold(
    body: HoldCreate,
    user: Annotated[dict[str, Any], Depends(current_user)],
    key: Annotated[str, Depends(idempotency.key_header)],
) -> Response:
    digest = idempotency.fingerprint(body.model_dump())
    async with db.connection() as conn, conn.transaction():
        replay = await idempotency.begin(conn, user["id"], key, OPERATION, digest)
        if replay is not None:
            return replay.response()
        hold = await _create(conn, user, body)
        headers = {"Location": f"/v1/holds/{hold['id']}", "ETag": f'"{hold["version"]}"'}
        await idempotency.complete(conn, user["id"], key, OPERATION, digest, 201, hold, headers)

    fault("after_commit_before_response")
    return JSONResponse(hold, status_code=201, headers=headers)


@router.get("/v1/holds")
async def list_holds(
    user: Annotated[dict[str, Any], Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    after_time, after_id = decode_cursor(cursor) if cursor else (None, None)
    async with db.connection() as conn:
        cur = await conn.execute(
            _HOLD_SELECT
            + """
            WHERE b.user_id = %(user)s
              AND (%(after_time)s::timestamptz IS NULL OR (b.created_at, b.id) < (%(after_time)s, %(after_id)s))
            ORDER BY b.created_at DESC, b.id DESC
            LIMIT %(limit)s
            """,
            {"user": user["id"], "after_time": after_time, "after_id": after_id, "limit": limit + 1},
        )
        rows = await cur.fetchall()
    page = rows[:limit]
    more = len(rows) > limit
    return {
        "items": [_view(r) for r in page],
        "next_cursor": encode_cursor(page[-1]["created_at"], page[-1]["id"]) if more else None,
    }


@router.patch("/v1/holds/{hold_id}")
async def update_hold(
    hold_id: str, body: HoldPatch, response: Response, user: Annotated[dict[str, Any], Depends(current_user)]
) -> dict[str, Any]:
    async with db.connection() as conn, conn.transaction():
        cur = await conn.execute(
            """
            UPDATE bookings SET holder_name = %s, version = version + 1
            WHERE id = %s AND user_id = %s AND status IN ('held', 'confirmed')
            RETURNING id
            """,
            (body.holder_name, hold_id, user["id"]),
        )
        if await cur.fetchone() is None:
            cur = await conn.execute(
                "SELECT status FROM bookings WHERE id = %s AND user_id = %s", (hold_id, user["id"])
            )
            current = await cur.fetchone()
            if current is None:
                raise Problem(404, "not-found", "Hold not found")
            raise Problem(
                409, "hold-not-editable", "Hold can no longer be changed", f"Its status is {current['status']}"
            )
        cur = await conn.execute(_HOLD_SELECT + " WHERE b.id = %s", (hold_id,))
        row = await cur.fetchone()
    response.headers["ETag"] = f'"{row["version"]}"'
    return _view(row)


@router.get("/v1/holds/{hold_id}")
async def get_hold(
    hold_id: str, response: Response, user: Annotated[dict[str, Any], Depends(current_user)]
) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(_HOLD_SELECT + " WHERE b.id = %s AND b.user_id = %s", (hold_id, user["id"]))
        row = await cur.fetchone()
    if row is None:
        raise Problem(404, "not-found", "Hold not found")
    response.headers["ETag"] = f'"{row["version"]}"'
    return _view(row)


async def sweep_forever() -> None:
    while True:
        await asyncio.sleep(config.HOLD_SWEEP_S)
        try:
            freed = 0
            async with db.connection() as conn:
                cur = await conn.execute(
                    """
                    SELECT DISTINCT category_id FROM bookings
                    WHERE status = 'held' AND hold_expires_at <= now() ORDER BY category_id LIMIT 50
                    """
                )
                categories = [r["category_id"] for r in await cur.fetchall()]
                for category_id in categories:
                    async with conn.transaction():
                        freed += await expire_due(conn, category_id)
            if freed:
                log("holds.expired", seats=freed, categories=len(categories))
        except (psycopg.Error, OSError) as exc:
            log("holds.sweep_failed", error=type(exc).__name__)
