"""Pool of long-lived MCP sessions, one per (user, server, resolved config).

Starting a stdio server can take seconds (``npx``/``uv run`` may install it
first), so sessions are kept open and reused across tool calls, then closed
after ``TOOL_SESSION_IDLE_SECONDS`` without use.

* **Owner task per session.** anyio transports must be entered and exited by
  the same task, so each session lives inside a dedicated task that opens it,
  signals ready, and waits to be told to close. Any request task may *use*
  the session; only its owner closes it.
* **Concurrent calls share a session.** MCP multiplexes requests by JSON-RPC
  id, so parallel workflow branches calling the same server don't queue.
* **Keyed by the resolved config's fingerprint** (credentials included): when
  a user reconnects with new credentials or an OAuth token refreshes, the next
  call opens a fresh session; the stale one just idles out.
* **Bounded:** at most ``TOOL_SESSION_MAX_PER_USER`` per user and
  ``TOOL_SESSION_MAX_OPEN`` overall; the least recently used idle session is
  closed to make room, and if none is idle the call fails fast.

There is one pool per event loop (tests run each on a fresh loop).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncContextManager, AsyncIterator, Callable

from mcp import ClientSession

from builder.config import get_builder_settings
from builder.services.tool_runtime.errors import ToolUnavailable

logger = logging.getLogger("builder.tool_runtime.pool")

SessionOpener = Callable[[], AsyncContextManager[ClientSession]]
_REAP_INTERVAL_SECONDS = 30.0
_CLOSE_GRACE_SECONDS = 10.0


@dataclass(eq=False)
class PooledSession:
    key: tuple[str, str, str]
    user_id: str
    label: str
    session: ClientSession | None = None
    in_use: int = 0
    last_used: float = field(default_factory=time.monotonic)
    dead: bool = False
    ready: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    close_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


class SessionPool:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], PooledSession] = {}
        self._guard = asyncio.Lock()
        self._reaper: asyncio.Task | None = None

    # ── public ──────────────────────────────────────────────────────────

    @asynccontextmanager
    async def acquire(
        self,
        key: tuple[str, str, str],
        *,
        user_id: str,
        label: str,
        opener: SessionOpener,
        connect_timeout: float,
    ) -> AsyncIterator[PooledSession]:
        entry = await self._get_or_open(key, user_id=user_id, label=label, opener=opener, connect_timeout=connect_timeout)
        entry.in_use += 1
        try:
            yield entry
        finally:
            entry.in_use -= 1
            entry.last_used = time.monotonic()

    async def evict(self, entry: PooledSession) -> None:
        """Close one session (its owner task exits the transport)."""
        async with self._guard:
            if self._entries.get(entry.key) is entry:
                del self._entries[entry.key]
        await self._close(entry)

    async def shutdown(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reaper
            self._reaper = None
        async with self._guard:
            entries = list(self._entries.values())
            self._entries.clear()
        await asyncio.gather(*(self._close(e) for e in entries), return_exceptions=True)

    def stats(self) -> dict[str, int]:
        return {"open": len(self._entries), "in_use": sum(1 for e in self._entries.values() if e.in_use)}

    # ── internals ───────────────────────────────────────────────────────

    async def _get_or_open(
        self,
        key: tuple[str, str, str],
        *,
        user_id: str,
        label: str,
        opener: SessionOpener,
        connect_timeout: float,
    ) -> PooledSession:
        async with self._guard:
            entry = self._entries.get(key)
            if entry is not None and entry.dead:
                del self._entries[key]
                entry = None
            if entry is None:
                await self._make_room(user_id)
                entry = PooledSession(key=key, user_id=user_id, label=label)
                # Read the future's outcome even if nobody awaits it (e.g. a
                # session that fails after its caller timed out).
                entry.ready.add_done_callback(lambda f: f.cancelled() or f.exception())
                entry.task = asyncio.create_task(self._own(entry, opener), name=f"mcp-session:{label}")
                self._entries[key] = entry
        self._ensure_reaper()

        # Wait outside the guard: starting a server can take a while and must
        # not block calls to other, already-open sessions.
        try:
            await asyncio.wait_for(asyncio.shield(entry.ready), timeout=connect_timeout)
        except TimeoutError:
            await self.evict(entry)
            raise ToolUnavailable(f"{label} didn't start within {connect_timeout:.0f}s.") from None
        except ToolUnavailable:
            raise
        except Exception as exc:
            await self.evict(entry)
            raise ToolUnavailable(f"Couldn't start {label}: {_describe(exc)}") from exc
        if entry.dead or entry.session is None:
            await self.evict(entry)
            raise ToolUnavailable(f"{label} stopped right after starting.")
        return entry

    async def _own(self, entry: PooledSession, opener: SessionOpener) -> None:
        try:
            async with opener() as session:
                entry.session = session
                if not entry.ready.done():
                    entry.ready.set_result(None)
                await entry.close_event.wait()
        except asyncio.CancelledError:
            if not entry.ready.done():
                entry.ready.set_exception(ToolUnavailable(f"Starting {entry.label} was cancelled."))
            raise
        except BaseException as exc:  # noqa: BLE001 — recorded on the entry, never lost
            if not entry.ready.done():
                entry.ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
            else:
                logger.info("mcp session %s ended: %s", entry.label, _describe(exc))
        finally:
            entry.dead = True
            entry.session = None

    async def _close(self, entry: PooledSession) -> None:
        entry.dead = True
        entry.close_event.set()
        task = entry.task
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_CLOSE_GRACE_SECONDS)
        except Exception:  # noqa: BLE001 — a wedged transport: force it down
            task.cancel()
            with contextlib.suppress(BaseException):
                await task

    async def _make_room(self, user_id: str) -> None:
        """Called under ``_guard``. Close idle sessions to respect the limits."""
        settings = get_builder_settings()
        for scope_user, limit in ((user_id, settings.TOOL_SESSION_MAX_PER_USER), (None, settings.TOOL_SESSION_MAX_OPEN)):
            open_entries = [e for e in self._entries.values() if scope_user is None or e.user_id == scope_user]
            if len(open_entries) < limit:
                continue
            idle = sorted((e for e in open_entries if e.in_use == 0), key=lambda e: e.last_used)
            if not idle:
                raise ToolUnavailable("Too many tool sessions are busy right now. Try again in a moment.")
            victim = idle[0]
            del self._entries[victim.key]
            asyncio.create_task(self._close(victim))

    def _ensure_reaper(self) -> None:
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_loop(), name="mcp-session-reaper")

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(_REAP_INTERVAL_SECONDS)
            await self.reap_idle()

    async def reap_idle(self, now: float | None = None) -> int:
        idle_for = get_builder_settings().TOOL_SESSION_IDLE_SECONDS
        now = time.monotonic() if now is None else now
        async with self._guard:
            stale = [e for e in self._entries.values() if e.dead or (e.in_use == 0 and now - e.last_used > idle_for)]
            for e in stale:
                del self._entries[e.key]
        for e in stale:
            await self._close(e)
        return len(stale)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_describe(e) for e in exc.exceptions)
    return str(exc) or exc.__class__.__name__


_pools: dict[int, SessionPool] = {}


def get_pool() -> SessionPool:
    loop = asyncio.get_running_loop()
    pool = _pools.get(id(loop))
    if pool is None:
        # Forget pools of loops that are gone (tests create one per test).
        for loop_id in [k for k in _pools if k != id(loop)]:
            _pools.pop(loop_id, None)
        pool = _pools[id(loop)] = SessionPool()
    return pool


async def shutdown_pool() -> None:
    loop = asyncio.get_running_loop()
    pool = _pools.pop(id(loop), None)
    if pool is not None:
        await pool.shutdown()


__all__ = ["PooledSession", "SessionPool", "get_pool", "shutdown_pool"]
