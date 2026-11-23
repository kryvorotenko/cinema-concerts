"""The API token: every /v1 route requires `Authorization: Bearer <API_TOKEN>`.

Use it as a router dependency: `APIRouter(prefix="/v1", dependencies=[Depends(require_token)])`.
"""

import hmac

from fastapi import Request

from . import config
from .problems import Problem


async def require_token(request: Request) -> None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), config.API_TOKEN.encode()):
        raise Problem(401, "unauthorized", "API token required", headers={"WWW-Authenticate": "Bearer"})


async def require_receiver_token(request: Request) -> None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), config.RECEIVER_TOKEN.encode()):
        raise Problem(401, "unauthorized", "Receiver token required", headers={"WWW-Authenticate": "Bearer"})


def _service_token(request: Request, expected: str, title: str) -> None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise Problem(401, "unauthorized", title, headers={"WWW-Authenticate": "Bearer"})


async def require_coordinator_token(request: Request) -> None:
    _service_token(request, config.COORDINATOR_TOKEN, "Coordinator token required")


async def require_web_reserve_token(request: Request) -> None:
    _service_token(request, config.WEB_RESERVE_TOKEN, "Web reserve token required")
