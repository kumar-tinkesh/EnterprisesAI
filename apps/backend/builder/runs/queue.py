"""How a run id reaches a worker.

The queue carries hints, not jobs: a message only means "run X may need
work". The worker that wins the run's DB lease does the work; everyone else
drops the message. So the queue may deliver twice, or lose a message — the
reaper re-enqueues anything the database says is stuck — without a run ever
being executed twice at once or forgotten.

That is also why a Redis message is acknowledged right after the claim
attempt instead of when the run finishes: a run can wait days on an
approval, and keeping its message pending that long buys nothing the
database lease doesn't already give.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Protocol

from builder.config import get_builder_settings

logger = logging.getLogger("builder.runs.queue")


class RunQueue(Protocol):
    async def enqueue(self, run_id: str) -> None: ...

    async def receive(self, timeout: float) -> str | None: ...

    async def close(self) -> None: ...


class LocalQueue:
    """In-process queue (inline mode and tests)."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def enqueue(self, run_id: str) -> None:
        self._queue.put_nowait(run_id)

    async def receive(self, timeout: float) -> str | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None

    def pending(self) -> int:
        return self._queue.qsize()

    async def close(self) -> None:
        pass


class RedisStreamQueue:
    """Redis Streams with one consumer group shared by every worker."""

    def __init__(self, url: str, stream: str, group: str, consumer: str | None = None):
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)
        self.stream = stream
        self.group = group
        self.consumer = consumer or f"{socket.gethostname()}-{os.getpid()}"
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        from redis.exceptions import ResponseError

        try:
            await self._redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    async def enqueue(self, run_id: str) -> None:
        await self._redis.xadd(self.stream, {"run_id": run_id}, maxlen=100_000, approximate=True)

    async def receive(self, timeout: float) -> str | None:
        await self._ensure_group()
        response = await self._redis.xreadgroup(
            self.group, self.consumer, {self.stream: ">"}, count=1, block=max(1, int(timeout * 1000))
        )
        if not response:
            return None
        _stream, entries = response[0]
        entry_id, fields = entries[0]
        # Acknowledged at once: the DB lease, not the pending list, guards the run.
        await self._redis.xack(self.stream, self.group, entry_id)
        await self._redis.xdel(self.stream, entry_id)
        return fields.get("run_id")

    async def close(self) -> None:
        await self._redis.aclose()


_queue: RunQueue | None = None


def get_run_queue() -> RunQueue:
    global _queue
    if _queue is None:
        settings = get_builder_settings()
        if settings.BUILDER_QUEUE_BACKEND == "redis":
            _queue = RedisStreamQueue(settings.REDIS_URL, settings.BUILDER_RUN_STREAM, settings.BUILDER_RUN_GROUP)
        else:
            _queue = LocalQueue()
    return _queue


def set_run_queue(queue: RunQueue | None) -> None:
    global _queue
    _queue = queue


async def enqueue_run(run_id: str) -> None:
    """Best-effort: if this fails the run stays queued in the DB and the reaper sends it later."""
    try:
        await get_run_queue().enqueue(run_id)
    except Exception:  # noqa: BLE001
        logger.warning("enqueue failed run=%s; the reaper will retry", run_id, exc_info=True)


__all__ = ["RunQueue", "LocalQueue", "RedisStreamQueue", "get_run_queue", "set_run_queue", "enqueue_run"]
