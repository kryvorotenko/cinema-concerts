import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import Header
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection

from . import config, db
from .jsonlog import log
from .problems import Problem

KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,255}$")


def key_header(idempotency_key: str | None = Header(default=None)) -> str:
    if idempotency_key is None or not idempotency_key.strip():
        raise Problem(400, "idempotency-key-required", "Idempotency-Key header is required")
    if not KEY_PATTERN.match(idempotency_key):
        raise Problem(
            400,
            "idempotency-key-invalid",
            "Idempotency-Key is invalid",
            "Use 1 to 255 printable ASCII characters without spaces",
        )
    return idempotency_key


def fingerprint(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class Replay:
    status_code: int
    body: Any
    location: str | None
    etag: str | None

    def response(self) -> JSONResponse:
        headers = {"Idempotent-Replayed": "true"}
        if self.location:
            headers["Location"] = self.location
        if self.etag:
            headers["ETag"] = self.etag
        return JSONResponse(self.body, status_code=self.status_code, headers=headers)


async def begin(conn: AsyncConnection, user_id: str, key: str, operation: str, digest: str) -> Replay | None:
    cur = await conn.execute(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS locked", (f"{user_id}:{len(user_id)}:{key}",)
    )
    if not (await cur.fetchone())["locked"]:
        raise Problem(
            409,
            "request-in-progress",
            "A request with this Idempotency-Key is still being processed",
            "Repeat the same request after the time in Retry-After",
            headers={"Retry-After": "1"},
        )

    cur = await conn.execute(
        """
        SELECT operation, fingerprint, status_code, response_body, location, etag, expires_at <= now() AS expired
        FROM idempotency_keys WHERE user_id = %s AND key = %s
        """,
        (user_id, key),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    if row["expired"]:
        await conn.execute("DELETE FROM idempotency_keys WHERE user_id = %s AND key = %s", (user_id, key))
        return None
    if row["operation"] != operation or row["fingerprint"] != digest:
        raise Problem(
            422,
            "idempotency-key-reused",
            "Idempotency-Key was already used with a different request",
            "Use a new key for a different request body",
        )
    return Replay(row["status_code"], row["response_body"], row["location"], row["etag"])


async def complete(
    conn: AsyncConnection,
    user_id: str,
    key: str,
    operation: str,
    digest: str,
    status_code: int,
    body: Any,
    headers: dict[str, str],
) -> None:
    await conn.execute(
        """
        INSERT INTO idempotency_keys
            (user_id, key, operation, fingerprint, status_code, response_body, location, etag, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, now() + make_interval(secs => %s))
        """,
        (
            user_id,
            key,
            operation,
            digest,
            status_code,
            json.dumps(body),
            headers.get("Location"),
            headers.get("ETag"),
            config.IDEMPOTENCY_TTL_S,
        ),
    )


async def purge_batch(conn: AsyncConnection) -> int:
    cur = await conn.execute(
        """
        DELETE FROM idempotency_keys
        WHERE (user_id, key) IN (
            SELECT user_id, key FROM idempotency_keys
            WHERE expires_at <= now()
            ORDER BY expires_at
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        """,
        (config.IDEMPOTENCY_PURGE_BATCH,),
    )
    return cur.rowcount


async def purge_forever() -> None:
    while True:
        await asyncio.sleep(config.IDEMPOTENCY_PURGE_S)
        try:
            removed = 0
            async with db.connection() as conn:
                while True:
                    async with conn.transaction():
                        batch = await purge_batch(conn)
                    removed += batch
                    if batch < config.IDEMPOTENCY_PURGE_BATCH:
                        break
            if removed:
                log("idempotency.purged", keys=removed)
        except (psycopg.Error, OSError) as exc:
            log("idempotency.purge_failed", error=type(exc).__name__)
