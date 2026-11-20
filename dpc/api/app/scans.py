"""DPC LR1 admission: bounded in-process queue and transactional sector effects."""

import asyncio
import random
from contextlib import suppress
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from . import auth, config, db, metrics
from .jsonlog import log
from .problems import Problem
from .queueing import AdmissionQueue


class ScanInput(BaseModel):
    scan_id: str = Field(min_length=1)
    ticket_id: str = Field(min_length=1)
    ticket_code: str = Field(min_length=1)
    gate: str = Field(min_length=1)
    sector_id: str = Field(min_length=1)
    event_time: datetime


class TicketResult(BaseModel):
    ticket_id: str
    performance_id: str
    valid: bool


router = APIRouter(prefix="/v1", dependencies=[Depends(auth.require_token)])


class Runtime:
    def __init__(self) -> None:
        self.queue = AdmissionQueue(config.QUEUE_CAPACITY)
        self.accepting = False
        self.busy = 0
        self.refused = 0
        self.tasks: list[asyncio.Task[None]] = []
        self.http = httpx.AsyncClient(timeout=config.TICKET_CHECK_TIMEOUT_S)

    async def start(self) -> None:
        if config.WORKERS < 1:
            raise ValueError("WORKERS must be positive")
        if config.TICKET_CHECK_MODE not in ("web", "fixture"):
            raise ValueError("TICKET_CHECK_MODE must be web or fixture")
        if config.RESOURCE_MODE == "unprotected" and config.TICKET_CHECK_MODE != "fixture":
            raise ValueError("unsafe mode requires fixture tickets")
        self.accepting = True
        self.tasks = [asyncio.create_task(self.worker(i)) for i in range(config.WORKERS)]
        metrics.gauge("queue_length", lambda: self.queue.queue.qsize())
        metrics.gauge("queue_capacity", lambda: self.queue.queue.maxsize)
        metrics.gauge("workers_busy", lambda: self.busy)
        metrics.gauge("scans_refused_total", lambda: self.refused)

    async def stop(self) -> None:
        self.accepting = False
        await self.queue.queue.join()
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):
                await task
        await self.http.aclose()

    async def worker(self, number: int) -> None:
        while True:
            scan_id = await self.queue.queue.get()  # asyncio suspends on an empty queue
            self.busy += 1
            try:
                await process(scan_id, self.http)
            except Exception as exc:
                log("scan.worker_error", scan_id=scan_id, error=type(exc).__name__, worker=number)
                try:
                    async with db.connection() as conn:
                        await conn.execute(
                            "UPDATE scans SET state='failed', error_code=%s, finished_at=now() WHERE id=%s AND state IN ('queued','processing')",
                            (type(exc).__name__, scan_id),
                        )
                        await conn.commit()
                except Exception as persist_error:
                    log("scan.failure_persist_error", scan_id=scan_id, error=type(persist_error).__name__)
            finally:
                self.busy -= 1
                self.queue.queue.task_done()


runtime = Runtime()


async def verify_ticket(row: dict, client: httpx.AsyncClient) -> TicketResult:
    # Slow external check is strictly outside the sector transaction.
    if config.TICKET_CHECK_MODE == "fixture":
        await asyncio.sleep(random.uniform(config.TICKET_CHECK_MIN_MS, config.TICKET_CHECK_MAX_MS) / 1000)
        async with db.connection() as conn:
            result = await conn.execute(
                "SELECT t.id AS ticket_id, b.screening_id AS performance_id,"
                " (t.status='valid' AND b.status='confirmed') AS valid"
                " FROM tickets t JOIN bookings b ON b.id=t.booking_id WHERE t.code=%s",
                (row["ticket_code"],),
            )
            ticket = await result.fetchone()
        return TicketResult(**ticket) if ticket else TicketResult(ticket_id=row["ticket_id"], performance_id="", valid=False)
    response = await client.get(
        f"{config.WEB_API_URL.rstrip('/')}/v1/tickets/{row['ticket_code']}",
        headers={"Authorization": f"Bearer {config.WEB_API_TOKEN}"},
    )
    if response.status_code == 404:
        return TicketResult(ticket_id=row["ticket_id"], performance_id="", valid=False)
    response.raise_for_status()
    return TicketResult.model_validate(response.json())


async def process(scan_id: str, client: httpx.AsyncClient) -> None:
    async with db.connection() as conn:
        async with conn.transaction():
            result = await conn.execute("UPDATE scans SET state='processing', started_at=now() WHERE id=%s AND state='queued' RETURNING *", (scan_id,))
            row = await result.fetchone()
    if row is None:
        return
    ticket = await verify_ticket(row, client)
    await apply_decision(row, ticket)


async def apply_decision(row: dict, ticket: TicketResult) -> None:
    async with db.connection() as conn:
        async with conn.transaction():
            # The ticket effect key is stable across distinct scan IDs.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (row["ticket_id"],))
            previous = await (await conn.execute(
                "SELECT decision FROM processed_effects WHERE handler='admission' AND effect_key=%s",
                (row["ticket_id"],),
            )).fetchone()
            if previous:
                decision = previous["decision"]
            else:
                unsafe = config.RESOURCE_MODE == "unprotected"
                if unsafe and not row["sector_id"].startswith("dpc-test-"):
                    raise RuntimeError("unsafe mode is limited to dpc-test- sectors")
                query = "SELECT id,screening_id,capacity,inside FROM sectors WHERE id=%s"
                if not unsafe:
                    query += " FOR UPDATE"
                sector = await (await conn.execute(query, (row["sector_id"],))).fetchone()
                if not sector:
                    raise RuntimeError("sector disappeared")
                accepted = (ticket.valid and ticket.ticket_id == row["ticket_id"]
                            and ticket.performance_id == sector["screening_id"]
                            and sector["inside"] < sector["capacity"])
                reason = "accepted" if accepted else (
                    "invalid_ticket" if not ticket.valid or ticket.ticket_id != row["ticket_id"] else
                    "wrong_performance" if ticket.performance_id != sector["screening_id"] else "sector_full"
                )
                if unsafe:
                    await asyncio.sleep(0.08)  # explicit race demonstration on isolated fixtures
                if accepted:
                    if unsafe:
                        await conn.execute("UPDATE sectors SET inside=%s WHERE id=%s", (sector["inside"] + 1, sector["id"]))
                    else:
                        await conn.execute("UPDATE sectors SET inside=inside+1 WHERE id=%s", (sector["id"],))
                decision = {"accepted": accepted, "reason": reason, "performance_id": sector["screening_id"], "sector_id": sector["id"]}
                await conn.execute(
                    "INSERT INTO processed_effects(handler,effect_key,event_id,decision) VALUES ('admission',%s,%s,%s)",
                    (row["ticket_id"], row["id"], Jsonb(decision)),
                )
            await conn.execute(
                "UPDATE scans SET state=%s, decision=%s, finished_at=now() WHERE id=%s",
                ("done" if decision["accepted"] else "rejected", Jsonb(decision), row["id"]),
            )


@router.post("/scans", status_code=202)
async def submit_scan(payload: ScanInput):
    if not runtime.accepting:
        raise Problem(503, "stopping", "Service is stopping", headers={"Retry-After": "1"})
    if payload.event_time.tzinfo is None:
        raise Problem(400, "invalid-event-time", "event_time must have a timezone")
    try:
        with runtime.queue.reserve() as enqueue:
            async with db.connection() as conn:
                async with conn.transaction():
                    sector = await (await conn.execute("SELECT 1 FROM sectors WHERE id=%s", (payload.sector_id,))).fetchone()
                    if sector is None:
                        raise Problem(404, "sector-not-found", "Sector not found")
                    existing = await (await conn.execute("SELECT * FROM scans WHERE id=%s", (payload.scan_id,))).fetchone()
                    if existing:
                        same = all(existing[k] == v for k, v in {
                            "ticket_id": payload.ticket_id, "ticket_code": payload.ticket_code,
                            "gate": payload.gate, "sector_id": payload.sector_id,
                            "event_time": payload.event_time.astimezone(timezone.utc),
                        }.items())
                        if not same:
                            raise Problem(409, "scan-id-conflict", "scan_id already has different content")
                        return {"scan_id": payload.scan_id, "state": existing["state"]}
                    inserted = await (await conn.execute(
                        "INSERT INTO scans(id,ticket_id,ticket_code,gate,sector_id,event_time,state) VALUES (%s,%s,%s,%s,%s,%s,'queued') ON CONFLICT (id) DO NOTHING RETURNING id",
                        (payload.scan_id, payload.ticket_id, payload.ticket_code, payload.gate,
                         payload.sector_id, payload.event_time),
                    )).fetchone()
                    if inserted is None:
                        raise Problem(409, "scan-id-conflict", "Concurrent scan_id submission; retry identical request")
            enqueue(payload.scan_id)
    except asyncio.QueueFull:
        runtime.refused += 1
        raise Problem(429, "queue-full", "Scan queue is full", headers={"Retry-After": "1"}) from None
    return {"scan_id": payload.scan_id, "state": "queued"}


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: str):
    async with db.connection() as conn:
        row = await (await conn.execute("SELECT * FROM scans WHERE id=%s", (scan_id,))).fetchone()
    if row is None:
        raise Problem(404, "scan-not-found", "Scan not found")
    return row


@router.get("/sector/{sector_id}")
async def get_sector(sector_id: str):
    async with db.connection() as conn:
        row = await (await conn.execute("SELECT id,screening_id AS performance_id,capacity,inside FROM sectors WHERE id=%s", (sector_id,))).fetchone()
    if row is None:
        raise Problem(404, "sector-not-found", "Sector not found")
    return row
