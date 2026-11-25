"""Ticket check for the DPC service: GET /v1/tickets/{code} (contract: docs/contracts/DPC-LR1.md).

Web issues tickets (Web LR4); DPC only reads them and redeems by ticket_id on its side.

`{code}` is the ticket code. The ticket id is accepted in the same place: the C01 card gives a scan
only `ticket_id` (no code), so DPC can check such a scan with `GET /v1/tickets/{ticket_id}`. If a value
is the code of one ticket and the id of another, the code wins; tickets issued in LR4 must keep the two
formats apart (code `TKT-...`, id a UUID), so that this never happens.
"""

from typing import Any

from fastapi import APIRouter, Depends

from . import db
from .auth import service_caller
from .problems import Problem

router = APIRouter(tags=["tickets"], dependencies=[Depends(service_caller)])


@router.get("/v1/tickets/{code}")
async def get_ticket(code: str) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(
            """
            SELECT t.id, t.status AS ticket_status, b.screening_id, b.status AS booking_status
            FROM tickets t JOIN bookings b ON b.id = t.booking_id
            WHERE t.code = %(value)s OR t.id = %(value)s
            ORDER BY (t.code = %(value)s) DESC
            LIMIT 1
            """,
            {"value": code},
        )
        row = await cur.fetchone()
    if row is None:
        raise Problem(404, "not-found", "Ticket not found")
    return {
        "ticket_id": row["id"],
        "performance_id": row["screening_id"],
        "valid": row["ticket_status"] == "valid" and row["booking_status"] == "confirmed",
    }
