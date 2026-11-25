import asyncio
import hashlib
import secrets
from datetime import datetime
from typing import Any

import psycopg
from psycopg import AsyncConnection

from . import config, db
from .jsonlog import log


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create(conn: AsyncConnection, user_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    cur = await conn.execute(
        """
        INSERT INTO sessions (token_hash, user_id, expires_at)
        VALUES (%s, %s, now() + make_interval(secs => %s))
        RETURNING expires_at
        """,
        (_digest(token), user_id, config.SESSION_TTL_S),
    )
    row = await cur.fetchone()
    return token, row["expires_at"]


async def user_of(conn: AsyncConnection, token: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        """
        SELECT u.id, u.email, u.display_name, u.role
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = %s AND s.expires_at > now()
        """,
        (_digest(token),),
    )
    return await cur.fetchone()


async def delete(conn: AsyncConnection, token: str) -> None:
    await conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_digest(token),))


async def purge_forever() -> None:
    while True:
        await asyncio.sleep(config.SESSION_PURGE_S)
        try:
            async with db.connection() as conn:
                cur = await conn.execute("DELETE FROM sessions WHERE expires_at <= now()")
                if cur.rowcount:
                    log("sessions.purged", sessions=cur.rowcount)
        except (psycopg.Error, OSError) as exc:
            log("sessions.purge_failed", error=type(exc).__name__)
