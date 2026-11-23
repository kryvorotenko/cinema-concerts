"""DPC LR2: CPU work in child processes, never in the API event loop."""

import asyncio
import math
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from .auth import require_token
from .numerics import T, partial, reference, split
from .problems import Problem

MAX_N = 20_000_000

router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])


class ComputeInput(BaseModel):
    a: float = Field(ge=0, le=T)
    b: float = Field(gt=0, le=T)
    n: int = Field(ge=1, le=MAX_N)
    workers: int = Field(ge=1, le=4)
    method: str
    order: int
    chunks_per_worker: int = Field(default=1, ge=1, le=16)

    @model_validator(mode="after")
    def valid_method(self):
        if not (math.isfinite(self.a) and math.isfinite(self.b) and self.a < self.b):
            raise ValueError("require finite 0 <= a < b <= 90")
        if (self.method, self.order) not in (("midpoint", 2), ("simpson", 4)):
            raise ValueError("method/order must be midpoint/2 or simpson/4")
        if self.n < self.workers * self.chunks_per_worker:
            raise ValueError("n must be at least workers * chunks_per_worker")
        return self


def calculate(a: float, b: float, n: int, workers: int, method: str,
              chunks_per_worker: int = 1) -> dict[str, float | int | str]:
    """Wall time includes pool creation, dispatch, transfer, reduction, and teardown."""
    started = time.perf_counter()
    width = (b - a) / n
    intervals = split(n, workers * chunks_per_worker)
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        futures = [pool.submit(partial, a, width, lo, hi, method) for lo, hi in intervals]
        parts = [future.result() for future in futures]
    value = math.fsum(parts)
    target = reference(a, b)
    return {
        "value": value, "reference": target, "error": abs(value - target),
        "time_s": time.perf_counter() - started, "workers": workers,
        "method": method, "order": 2 if method == "midpoint" else 4,
        "n": n, "chunks_per_worker": chunks_per_worker,
    }


@router.post("/compute")
async def compute(payload: ComputeInput):
    try:
        return await asyncio.to_thread(
            calculate, payload.a, payload.b, payload.n, payload.workers,
            payload.method, payload.chunks_per_worker,
        )
    except (OSError, RuntimeError) as exc:
        raise Problem(503, "compute-unavailable", "Compute pool unavailable", error_class=type(exc).__name__) from exc
