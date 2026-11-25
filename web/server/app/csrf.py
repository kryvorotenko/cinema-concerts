from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config
from .problems import Problem

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed(origin: str | None, site: str | None) -> bool:
    if site == "same-origin":
        return True
    if origin is not None:
        return origin == config.CLIENT_ORIGIN
    return site in (None, "none")


class CsrfGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if allowed(headers.get("origin"), headers.get("sec-fetch-site")):
            await self.app(scope, receive, send)
            return
        problem = Problem(
            403,
            "csrf-rejected",
            "Request from a foreign origin",
            "State-changing requests are accepted only from the client origin",
        )
        await problem.response(scope["path"])(scope, receive, send)
