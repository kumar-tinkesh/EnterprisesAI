"""Redis Streams queue and pub/sub events against a real Redis.

Skipped unless BUILDER_TEST_REDIS_URL points at a Redis you don't mind
writing to (it uses its own stream/channel names and deletes them), e.g.:

    docker run -d --rm -p 6390:6379 redis:7-alpine
    BUILDER_TEST_REDIS_URL=redis://localhost:6390/0 uv run pytest apps/backend/builder/tests/test_redis_backend.py
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from builder.runs.events import RedisEventBus
from builder.runs.queue import RedisStreamQueue

REDIS_URL = os.environ.get("BUILDER_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="set BUILDER_TEST_REDIS_URL to run against a real Redis")


async def test_stream_queue_delivers_each_message_to_one_worker():
    stream, group = f"test:runs:{uuid.uuid4().hex}", "test-workers"
    a = RedisStreamQueue(REDIS_URL, stream, group, consumer="a")
    b = RedisStreamQueue(REDIS_URL, stream, group, consumer="b")
    try:
        assert await a.receive(timeout=0.1) is None  # creates the group
        for i in range(6):
            await a.enqueue(f"run-{i}")
        got = []
        for _ in range(6):
            for q in (a, b):
                run_id = await q.receive(timeout=0.5)
                if run_id:
                    got.append(run_id)
        assert sorted(got) == [f"run-{i}" for i in range(6)]  # every one, once
        assert await a.receive(timeout=0.1) is None and await b.receive(timeout=0.1) is None
        # Acknowledged and deleted on receipt: nothing left pending.
        assert (await a._redis.xpending(stream, group))["pending"] == 0
    finally:
        await a._redis.delete(stream)
        await a.close()
        await b.close()


async def test_events_reach_subscribers_in_other_processes():
    publisher, listener = RedisEventBus(REDIS_URL), RedisEventBus(REDIS_URL)
    run_id = uuid.uuid4().hex
    try:
        async with listener.subscribe(run_id) as sub:
            await asyncio.sleep(0.1)
            await publisher.publish(run_id, {"type": "run_status", "run_id": run_id, "status": "running"})
            event = await sub.get(timeout=2)
            while event is None:
                event = await sub.get(timeout=2)
            assert event == {"type": "run_status", "run_id": run_id, "status": "running"}
            await publisher.publish("another-run", {"type": "noise"})
            assert await sub.get(timeout=0.3) is None
    finally:
        await publisher.close()
        await listener.close()
