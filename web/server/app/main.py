"""The API process (app-a, app-b): `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

Your work goes into new modules that you include below. Where each lab plugs in:
  DONE (O1.4, O1.5) catalog.py, holds.py (create hold, list with a cursor), tickets.py (DPC ticket check)
  DONE (O2.1-O2.3)  conditional UPDATE, idempotency.py, fault("after_commit_before_response") in holds.py
  DONE (O3.1-O3.3)  auth.py (login, logout, me), sessions.py, csrf.py, PATCH /v1/holds/{id}, staff close-sales
  TODO (O4.1-O4.4)  long operation, outbox in the same transaction (publisher and handler are
                    separate processes: app/publisher.py, app/worker.py)
  TODO (O5.1)       POST /v1/ws-tickets; the gateway itself is app/gateway.py
  TODO (O6.3)       SIGTERM: lifecycle.start_draining(), finish started requests
The contract of all routes is your openapi.yaml (start from openapi.example.yaml).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import (
    auth,
    cache,
    catalog,
    config,
    db,
    holds,
    idempotency,
    metrics,
    middleware,
    problems,
    service,
    sessions,
    telemetry,
    tickets,
)
from .csrf import CsrfGuard
from .jsonlog import log


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await db.open_pool()

    tasks = [
        asyncio.create_task(holds.sweep_forever()),
        asyncio.create_task(idempotency.purge_forever()),
        asyncio.create_task(sessions.purge_forever()),
    ]
    log("app.started")
    yield

    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await cache.close()
    await db.close_pool()

    log("app.stopped")


# The contract is openapi.yaml of your repository, so the generated schema routes are off.
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CsrfGuard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.CLIENT_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "If-Match", "X-Request-ID"],
    expose_headers=["Location", "ETag", "Retry-After", "X-Request-ID", "X-Instance", "Idempotent-Replayed"],
)
middleware.install(app)
problems.install(app)
app.include_router(service.router)
app.include_router(metrics.router)
telemetry.install(app)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(holds.router)
app.include_router(tickets.router)
