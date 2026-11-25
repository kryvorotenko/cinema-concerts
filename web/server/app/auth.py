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
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), config.WEB_API_TOKEN.encode()):
        raise Problem(401, "unauthenticated", "Service token required", headers={"WWW-Authenticate": "Bearer"})
