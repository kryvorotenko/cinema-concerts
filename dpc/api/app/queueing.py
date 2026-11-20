"""Bounded admission queue: reserve capacity before awaiting durable acceptance.

One instance belongs to one asyncio event loop. Reservation is synchronous;
waiting for a queue item suspends the worker rather than occupying a thread.
"""
import asyncio
from contextlib import contextmanager


class AdmissionQueue:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError('capacity must be positive')
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=capacity)
        self.reserved = 0

    @contextmanager
    def reserve(self):
        if self.queue.qsize() + self.reserved >= self.queue.maxsize:
            raise asyncio.QueueFull
        self.reserved += 1
        try:
            yield self.queue.put_nowait
        finally:
            self.reserved -= 1
