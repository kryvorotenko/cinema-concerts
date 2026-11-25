from typing import Any

from fastapi import APIRouter, Depends

from . import db
from .auth import current_user, staff_user
from .formats import iso, money
from .problems import Problem

router = APIRouter(tags=["catalog"], dependencies=[Depends(current_user)])


@router.get("/v1/events")
async def list_events() -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(
            """
            SELECT s.id, s.event_id, e.title, e.kind, s.starts_at, s.duration_min, s.status,
                   v.id AS venue_id, v.name AS venue_name, v.city, v.time_zone
            FROM screenings s
            JOIN events e ON e.id = s.event_id
            JOIN venues v ON v.id = s.venue_id
            ORDER BY s.starts_at, s.id
            LIMIT 100
            """
        )
        rows = await cur.fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "event_id": r["event_id"],
                "title": r["title"],
                "kind": r["kind"],
                "starts_at": iso(r["starts_at"]),
                "duration_min": r["duration_min"],
                "status": r["status"],
                "venue": {"id": r["venue_id"], "name": r["venue_name"], "city": r["city"], "time_zone": r["time_zone"]},
            }
            for r in rows
        ]
    }


def _category(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "performance_id": r["screening_id"],
        "name": r["name"],
        "capacity": r["capacity"],
        "available": r["available"],
        "price": money(r["price_minor"], r["currency"]),
        "sales_open": r["sales_open"],
    }


@router.get("/v1/events/{performance_id}/categories")
async def list_categories(performance_id: str) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute("SELECT 1 FROM screenings WHERE id = %s", (performance_id,))
        if await cur.fetchone() is None:
            raise Problem(404, "not-found", "Performance not found")
        cur = await conn.execute(
            """
            SELECT id, screening_id, name, capacity, available, price_minor, currency, sales_open
            FROM seat_categories WHERE screening_id = %s ORDER BY price_minor DESC, id
            """,
            (performance_id,),
        )
        rows = await cur.fetchall()
    return {"items": [_category(r) for r in rows]}


async def _set_sales(category_id: str, open_: bool) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(
            """
            UPDATE seat_categories SET sales_open = %s WHERE id = %s
            RETURNING id, screening_id, name, capacity, available, price_minor, currency, sales_open
            """,
            (open_, category_id),
        )
        row = await cur.fetchone()
    if row is None:
        raise Problem(404, "not-found", "Category not found")
    return _category(row)


@router.post("/v1/categories/{category_id}/close-sales", dependencies=[Depends(staff_user)])
async def close_sales(category_id: str) -> dict[str, Any]:
    return await _set_sales(category_id, False)


@router.post("/v1/categories/{category_id}/open-sales", dependencies=[Depends(staff_user)])
async def open_sales(category_id: str) -> dict[str, Any]:
    return await _set_sales(category_id, True)
