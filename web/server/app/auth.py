"""Who is calling (Web LR1).

Until Web LR3 the user is named by the X-User-Id header and must exist in `users`. The owner of
every object comes from here, never from a request body. LR3 replaces `current_user` with a
session/token check and removes the header.
"""

import secrets
from typing import Any

from fastapi import Header

from . import config, db
from .problems import Problem


async def current_user(x_user_id: str | None = Header(default=None)) -> dict[str, Any]:
    if not x_user_id:
        raise Problem(401, "unauthenticated", "Authentication required", "Header X-User-Id is missing")
    async with db.connection() as conn:
        cur = await conn.execute("SELECT id, role, display_name FROM users WHERE id = %s", (x_user_id,))
        user = await cur.fetchone()
    if user is None:
        raise Problem(401, "unauthenticated", "Authentication required", "Unknown user")
    return user


async def service_caller(authorization: str | None = Header(default=None)) -> None:
    """Bearer WEB_API_TOKEN: the DPC service asks Web about tickets (docs/contracts/DPC-LR1.md)."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), config.WEB_API_TOKEN.encode()):
        raise Problem(401, "unauthenticated", "Service token required", headers={"WWW-Authenticate": "Bearer"})
