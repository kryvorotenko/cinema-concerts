"""Fenced assignment of Web-pre-reserved returned seats to DPC waitlist buyers."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import auth, db
from .problems import Problem

router = APIRouter(prefix="/v1", dependencies=[Depends(auth.require_token)])
coordinator_router = APIRouter(prefix="/internal/coordinator", dependencies=[Depends(auth.require_coordinator_token)], include_in_schema=False)
web_router = APIRouter(prefix="/internal/waitlist", dependencies=[Depends(auth.require_web_reserve_token)], include_in_schema=False)


class WaitlistInput(BaseModel):
    waitlist_id: str = Field(min_length=1)
    performance_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)


class ReserveInput(BaseModel):
    web_reserve_id: str = Field(min_length=1)
    performance_id: str = Field(min_length=1)
    seat_id: str = Field(min_length=1)


class RegisterInput(BaseModel):
    owner: str = Field(min_length=1)
    generation: int = Field(gt=0)


class AssignInput(RegisterInput):
    assignment_id: str = Field(min_length=1)
    web_reserve_id: str = Field(min_length=1)
    waitlist_id: str = Field(min_length=1)


@router.post("/waitlist", status_code=201)
async def join_waitlist(payload: WaitlistInput):
    async with db.connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute(
                "INSERT INTO waitlist_entries(id,performance_id,buyer_id) VALUES (%s,%s,%s)"
                " ON CONFLICT DO NOTHING RETURNING id",
                (payload.waitlist_id, payload.performance_id, payload.buyer_id),
            )).fetchone()
            if row is None:
                raise Problem(409, "waitlist-conflict", "Waitlist entry already exists")
    return {"waitlist_id": payload.waitlist_id, "status": "waiting"}


@web_router.post("/reserves", status_code=201)
async def receive_web_reserve(payload: ReserveInput):
    """Web calls only after it has reserved a returned seat from sale."""
    async with db.connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute(
                "INSERT INTO returned_reserves(web_reserve_id,performance_id,seat_id)"
                " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING web_reserve_id",
                (payload.web_reserve_id, payload.performance_id, payload.seat_id),
            )).fetchone()
            if row is None:
                raise Problem(409, "reserve-conflict", "Web reserve already exists")
    return {"web_reserve_id": payload.web_reserve_id, "status": "ready"}


@web_router.get("/assignments/{web_reserve_id}")
async def assignment_for_web(web_reserve_id: str):
    async with db.connection() as conn:
        row = await (await conn.execute(
            "SELECT a.assignment_id,a.web_reserve_id,a.waitlist_id,w.buyer_id,"
            " r.performance_id,r.seat_id,a.generation,a.assigned_at"
            " FROM waitlist_assignments a JOIN returned_reserves r USING (web_reserve_id)"
            " JOIN waitlist_entries w ON w.id=a.waitlist_id WHERE a.web_reserve_id=%s",
            (web_reserve_id,),
        )).fetchone()
    if row is None:
        raise Problem(404, "assignment-not-found", "Assignment not ready")
    return row


@coordinator_router.post("/register")
async def register(payload: RegisterInput):
    async with db.connection() as conn:
        async with conn.transaction():
            state = await (await conn.execute(
                "SELECT generation,owner FROM coordination_state WHERE id='waitlist' FOR UPDATE"
            )).fetchone()
            if payload.generation > state["generation"]:
                await conn.execute(
                    "UPDATE coordination_state SET generation=%s,owner=%s,registered_at=now() WHERE id='waitlist'",
                    (payload.generation, payload.owner),
                )
                await conn.execute(
                    "INSERT INTO coordination_history(kind,generation,owner) VALUES ('register',%s,%s)",
                    (payload.generation, payload.owner),
                )
                return {"owner": payload.owner, "generation": payload.generation, "registered": True}
            same = payload.generation == state["generation"] and payload.owner == state["owner"]
    if not same:
        raise Problem(409, "stale-generation", "Generation is not newer than registered generation")
    return {"owner": payload.owner, "generation": payload.generation, "registered": True}


@coordinator_router.get("/next")
async def next_assignment():
    async with db.connection() as conn:
        row = await (await conn.execute(
            "SELECT r.web_reserve_id,w.id AS waitlist_id FROM returned_reserves r"
            " JOIN LATERAL (SELECT id FROM waitlist_entries WHERE performance_id=r.performance_id"
            " AND status='waiting' ORDER BY created_at,id LIMIT 1) w ON true"
            " WHERE r.status='ready' ORDER BY r.received_at,r.web_reserve_id LIMIT 1"
        )).fetchone()
    return row or {"web_reserve_id": None, "waitlist_id": None}


@coordinator_router.post("/assign")
async def assign(payload: AssignInput):
    failure = None
    async with db.connection() as conn:
        async with conn.transaction():
            state = await (await conn.execute(
                "SELECT generation,owner FROM coordination_state WHERE id='waitlist' FOR UPDATE"
            )).fetchone()
            if state["generation"] != payload.generation or state["owner"] != payload.owner:
                failure = "stale_generation"
            else:
                reserve = await (await conn.execute(
                    "SELECT performance_id,status FROM returned_reserves WHERE web_reserve_id=%s FOR UPDATE",
                    (payload.web_reserve_id,),
                )).fetchone()
                buyer = await (await conn.execute(
                    "SELECT performance_id,status FROM waitlist_entries WHERE id=%s FOR UPDATE",
                    (payload.waitlist_id,),
                )).fetchone()
                if not reserve or not buyer or reserve["performance_id"] != buyer["performance_id"]:
                    failure = "invalid_pair"
                elif reserve["status"] != "ready" or buyer["status"] != "waiting":
                    old = await (await conn.execute(
                        "SELECT assignment_id FROM waitlist_assignments WHERE web_reserve_id=%s",
                        (payload.web_reserve_id,),
                    )).fetchone()
                    if old and old["assignment_id"] == payload.assignment_id:
                        return {"assignment_id": payload.assignment_id, "status": "assigned", "replayed": True}
                    failure = "already_assigned"
                else:
                    await conn.execute(
                        "INSERT INTO waitlist_assignments(assignment_id,web_reserve_id,waitlist_id,generation,owner)"
                        " VALUES (%s,%s,%s,%s,%s)",
                        (payload.assignment_id, payload.web_reserve_id, payload.waitlist_id,
                         payload.generation, payload.owner),
                    )
                    await conn.execute("UPDATE returned_reserves SET status='assigned' WHERE web_reserve_id=%s", (payload.web_reserve_id,))
                    await conn.execute("UPDATE waitlist_entries SET status='assigned' WHERE id=%s", (payload.waitlist_id,))
                    await conn.execute(
                        "INSERT INTO coordination_history(kind,generation,owner,web_reserve_id,waitlist_id)"
                        " VALUES ('assigned',%s,%s,%s,%s)",
                        (payload.generation, payload.owner, payload.web_reserve_id, payload.waitlist_id),
                    )
                    return {"assignment_id": payload.assignment_id, "status": "assigned", "replayed": False}
            await conn.execute(
                "INSERT INTO coordination_history(kind,generation,owner,web_reserve_id,waitlist_id,reason)"
                " VALUES ('rejected',%s,%s,%s,%s,%s)",
                (payload.generation, payload.owner, payload.web_reserve_id, payload.waitlist_id, failure),
            )
    raise Problem(409, failure.replace("_", "-"), "Assignment rejected", detail=failure)


@router.get("/coordinator")
async def coordinator_status():
    async with db.connection() as conn:
        row = await (await conn.execute(
            "SELECT owner,generation,registered_at FROM coordination_state WHERE id='waitlist'"
        )).fetchone()
    return row


@router.get("/history")
async def history():
    async with db.connection() as conn:
        rows = await (await conn.execute(
            "SELECT * FROM coordination_history ORDER BY id"
        )).fetchall()
    return {"items": rows}
