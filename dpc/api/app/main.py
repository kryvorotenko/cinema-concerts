"""The `api` process: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

Where each lab plugs in (item numbers of the guide):
  DONE (O1.1-O1.4) the scan queue, worker pool and protected sector effect.
  DONE (O2.1/O2.3/O2.4) POST /v1/compute and reproducible process experiments.
  TODO (O1.5, D1.4; O2.2, D2.1-D2.6) optional extensions are not selected.
  DONE (O3.1/O3.3/O3.4) Ray tasks, transactional receiver, and worker retry fault.
  TODO (O3.2, D3.1-D3.4) optional Ray extensions are not selected.
  TODO (O4.2)       POST /v1/reports/main/refresh calls the given Spark runner (RUNNER_URL)
  TODO (O5.x)       GET /v1/panel, /v1/panel/batch: the windows written by your stream job
  DONE (O6.1/O6.2) etcd lease leaders, resource generation registry, fenced waitlist assignment.
  TODO (O6.3, D6.x) optional coordination extensions are not selected.
Protect your /v1 routers with `dependencies=[Depends(auth.require_token)]`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import compute, config, coordination, db, middleware, problems, service, scans
from .jsonlog import log


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await db.open_pool()
    await scans.runtime.start()
    log("api.started")

    yield

    await scans.runtime.stop()
    await db.close_pool()
    log("api.stopped")


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
middleware.install(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.CLIENT_ORIGIN],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    expose_headers=["Location", "Retry-After", "X-Request-ID"],
)
problems.install(app)
app.include_router(service.router)
app.include_router(scans.router)
app.include_router(scans.internal_router)
app.include_router(compute.router)
app.include_router(coordination.router)
app.include_router(coordination.coordinator_router)
app.include_router(coordination.web_router)
