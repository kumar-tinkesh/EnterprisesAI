"""Live run events for WebSocket clients.

Events are a convenience, not the record: everything they say is also in the
database (run status, node runs, tool calls, approvals), and a client that
connects late gets a snapshot from there first. So losing an event (a client
reconnecting, Redis restarting) never loses information.

Each event is a JSON object with ``type`` and ``run_id``, e.g.
``{"type": "tool_call", "phase": "finished", "tool": "send_email", ...}``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol

from builder.config import get_builder_settings

logger = logging.getLogger("builder.runs.events")


class EventBus(Protocol):
    async def publish(self, run_id: str, event: dict) -> None: ...

    def subscribe(self, run_id: str) -> AsyncIterator["Subscription"]: ...

    async def close(self) -> None: ...


class Subscription(Protocol):
    async def get(self, timeout: float) -> dict | None: ...


class _QueueSubscription:
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    async def get(self, timeout: float) -> dict | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except TimeoutError:
            return None


class LocalEventBus:
    """In-process fan-out (inline mode and tests)."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, run_id: str, event: dict) -> None:
        for queue in list(self._subscribers.get(run_id, ())):
            if queue.qsize() < 1000:  # a stalled client must not grow memory forever
                queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[_QueueSubscription]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[run_id].add(queue)
        try:
            yield _QueueSubscription(queue)
        finally:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

    async def close(self) -> None:
        self._subscribers.clear()


class _RedisSubscription:
    def __init__(self, pubsub):
        self.pubsub = pubsub

    async def get(self, timeout: float) -> dict | None:
        message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if not message:
            return None
        try:
            return json.loads(message["data"])
        except (TypeError, ValueError):
            return None


class RedisEventBus:
    """Redis pub/sub: workers publish, any API process forwards to its sockets."""

    def __init__(self, url: str):
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)

    @staticmethod
    def _channel(run_id: str) -> str:
        return f"builder:run-events:{run_id}"

    async def publish(self, run_id: str, event: dict) -> None:
        try:
            await self._redis.publish(self._channel(run_id), json.dumps(event, default=str))
        except Exception:  # noqa: BLE001 — events are best-effort, the DB is the record
            logger.warning("run event publish failed run=%s", run_id, exc_info=True)

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[_RedisSubscription]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(run_id))
        try:
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.unsubscribe(self._channel(run_id))
            await pubsub.aclose()

    async def close(self) -> None:
        await self._redis.aclose()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        settings = get_builder_settings()
        _bus = RedisEventBus(settings.REDIS_URL) if settings.BUILDER_QUEUE_BACKEND == "redis" else LocalEventBus()
    return _bus


def set_event_bus(bus: EventBus | None) -> None:
    global _bus
    _bus = bus


async def emit(run_id: str, type_: str, **data) -> None:
    await get_event_bus().publish(run_id, {"type": type_, "run_id": run_id, **data})


__all__ = ["EventBus", "LocalEventBus", "RedisEventBus", "get_event_bus", "set_event_bus", "emit"]
