"""Runs a minute per IP address on the public API and share links — one more
fence besides each key's own limits, against one machine trying many keys or
many sign-ups.

Counted in Redis when runs go through Redis (so every API process shares the
count), in this process otherwise. Fixed one-minute windows: simple, and
close enough for a fence.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

from builder.config import get_builder_settings

_local: dict[tuple[str, int], int] = defaultdict(int)
_redis = None


def client_ip(request: Request) -> str:
    if get_builder_settings().TRUST_FORWARDED_FOR:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _count(ip: str, window: int) -> int:
    global _redis
    settings = get_builder_settings()
    if settings.BUILDER_QUEUE_BACKEND == "redis":
        if _redis is None:
            import redis.asyncio as redis

            _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        key = f"builder:public-ip:{ip}:{window}"
        count = await _redis.incr(key)
        if count == 1:
            await _redis.expire(key, 120)
        return int(count)
    for stale in [k for k in _local if k[1] < window]:
        del _local[stale]
    _local[(ip, window)] += 1
    return _local[(ip, window)]


async def check_ip_limit(request: Request) -> None:
    """Raises 429 once this address has started its share of runs this minute."""
    limit = get_builder_settings().PUBLIC_RUNS_PER_IP_PER_MINUTE
    if limit <= 0:
        return
    if await _count(client_ip(request), int(time.time() // 60)) > limit:
        raise HTTPException(status_code=429, detail="Too many requests from your network. Try again in a minute.")


def reset_local_counts() -> None:
    """Tests: start from zero."""
    _local.clear()


__all__ = ["check_ip_limit", "client_ip", "reset_local_counts"]
