import asyncio
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from . import config, db, sessions
from .passwords import DUMMY_HASH, verify_password
from .problems import Problem

router = APIRouter(tags=["auth"])


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _person(user: dict[str, Any]) -> dict[str, Any]:
    return {"id": user["id"], "name": user["display_name"], "email": user["email"], "role": user["role"]}


def _unauthenticated(detail: str) -> Problem:
    return Problem(401, "unauthenticated", "Authentication required", detail)


async def session_token(session: Annotated[str | None, Cookie(alias=config.SESSION_COOKIE)] = None) -> str:
    if not session:
        raise _unauthenticated("No session")
    return session


async def current_user(token: Annotated[str, Depends(session_token)]) -> dict[str, Any]:
    async with db.connection() as conn:
        user = await sessions.user_of(conn, token)
    if user is None:
        raise _unauthenticated("The session is unknown or has expired")
    return user


async def staff_user(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    if user["role"] != "staff":
        raise Problem(403, "forbidden", "Staff role required")
    return user


async def service_caller(authorization: str | None = Header(default=None)) -> None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), config.WEB_API_TOKEN.encode()):
        raise Problem(401, "unauthenticated", "Service token required", headers={"WWW-Authenticate": "Bearer"})


@router.post("/v1/auth/login")
async def login(body: Credentials, response: Response) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT id, email, display_name, role, password_hash FROM users WHERE lower(email) = lower(%s)",
            (body.login,),
        )
        user = await cur.fetchone()
    stored = user["password_hash"] if user else DUMMY_HASH
    valid = await asyncio.to_thread(verify_password, body.password, stored)
    if user is None or not valid:
        raise Problem(401, "invalid-credentials", "Invalid login or password")

    async with db.connection() as conn, conn.transaction():
        token, _ = await sessions.create(conn, user["id"])
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=config.SESSION_TTL_S,
        path="/",
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
    )
    response.headers["Cache-Control"] = "no-store"
    return _person(user)


@router.post("/v1/auth/logout", status_code=204, response_class=Response)
async def logout(
    response: Response,
    token: Annotated[str, Depends(session_token)],
    user: Annotated[dict[str, Any], Depends(current_user)],
) -> None:
    async with db.connection() as conn:
        await sessions.delete(conn, token)
    response.delete_cookie(config.SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=config.COOKIE_SECURE)


@router.get("/v1/me")
async def me(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    return _person(user)
