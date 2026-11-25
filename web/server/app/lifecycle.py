import asyncio
import json
import signal
from collections.abc import Callable

from starlette.types import ASGIApp, Receive, Scope, Send

from . import config
from .jsonlog import log

OPEN_PATHS = {"/health", "/ready", "/metrics"}

_draining = False
_inflight = 0


def start_draining() -> None:
    global _draining
    _draining = True


def is_draining() -> bool:
    return _draining


def inflight() -> int:
    return _inflight


class DrainGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        global _inflight
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        if _draining:
            body = json.dumps(
                {
                    "type": config.PROBLEM_BASE + "shutting-down",
                    "title": "This instance is shutting down",
                    "status": 503,
                    "instance": scope["path"],
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"retry-after", b"1"),
                        (b"connection", b"close"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        _inflight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            _inflight -= 1


async def _drain_then_stop(stop: Callable[[int, object], None]) -> None:
    start_draining()
    log("shutdown.draining", inflight=_inflight, delay_s=config.DRAIN_DELAY_S)
    await asyncio.sleep(config.DRAIN_DELAY_S)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + config.DRAIN_TIMEOUT_S
    while _inflight and loop.time() < deadline:
        await asyncio.sleep(0.05)
    log("shutdown.stopping", inflight=_inflight, timed_out=bool(_inflight))
    stop(signal.SIGTERM, None)


def install_sigterm() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    if not callable(previous):
        return
    loop = asyncio.get_running_loop()
    tasks: list[asyncio.Task[None]] = []

    def on_term() -> None:
        if tasks:
            previous(signal.SIGTERM, None)
            return
        tasks.append(loop.create_task(_drain_then_stop(previous)))

    loop.add_signal_handler(signal.SIGTERM, on_term)
