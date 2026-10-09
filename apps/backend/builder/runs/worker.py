"""The worker: take run ids off the queue, win the lease, execute, let go.

    worker = Worker(); await worker.start(); ...; await worker.stop()

* Up to ``WORKER_CONCURRENCY`` runs at once.
* While a run executes, a heartbeat renews its lease every
  ``RUN_HEARTBEAT_SECONDS``. If renewal fails — the run was cancelled, or this
  worker stalled long enough for another to take over — the execution is
  cancelled at once; whatever it checkpointed stays for the next holder.
* The schedule loop (every ``SCHEDULE_POLL_SECONDS``) starts due scheduled
  runs; every worker runs one, and each occurrence is claimed by exactly one.
* The reaper (every ``RUN_REAPER_INTERVAL_SECONDS``) re-enqueues runs whose
  lease lapsed (their worker died) and queued runs whose message was lost.
  Every worker runs one; duplicates are harmless because of the lease.
* On ``stop()`` in-flight executions are cancelled, not finished: their leases
  lapse and another worker resumes them from their checkpoints.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import uuid

from builder.config import get_builder_settings
from builder.runs import executor, lease
from builder.runs.queue import RunQueue, get_run_queue

logger = logging.getLogger("builder.runs.worker")


class Worker:
    def __init__(self, *, queue: RunQueue | None = None, worker_id: str | None = None, concurrency: int | None = None):
        settings = get_builder_settings()
        self.queue = queue or get_run_queue()
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.concurrency = concurrency or settings.WORKER_CONCURRENCY
        self._slots = asyncio.Semaphore(self.concurrency)
        self._active: set[asyncio.Task] = set()
        self._loops: list[asyncio.Task] = []
        self._stopping = False

    # ── lifecycle ──

    async def start(self, *, reaper: bool = True, schedules: bool | None = None) -> None:
        self._stopping = False
        self._loops.append(asyncio.create_task(self._consume_loop(), name=f"worker-consume:{self.worker_id}"))
        if reaper:
            self._loops.append(asyncio.create_task(self._reaper_loop(), name=f"worker-reaper:{self.worker_id}"))
        if schedules is None:
            schedules = get_builder_settings().BUILDER_SCHEDULER_ENABLED
        if schedules:
            self._loops.append(asyncio.create_task(self._schedule_loop(), name=f"worker-schedules:{self.worker_id}"))
        logger.info("builder worker %s started (concurrency=%d)", self.worker_id, self.concurrency)

    async def stop(self) -> None:
        self._stopping = True
        for task in [*self._loops, *self._active]:
            task.cancel()
        for task in [*self._loops, *self._active]:
            with contextlib.suppress(BaseException):
                await task
        self._loops.clear()
        self._active.clear()

    # ── loops ──

    async def _consume_loop(self) -> None:
        while not self._stopping:
            await self._slots.acquire()
            try:
                run_id = await self.queue.receive(timeout=1.0)
            except asyncio.CancelledError:
                self._slots.release()
                raise
            except Exception:  # noqa: BLE001 — e.g. Redis briefly unreachable
                self._slots.release()
                logger.warning("queue receive failed; retrying", exc_info=True)
                await asyncio.sleep(1.0)
                continue
            if run_id is None:
                self._slots.release()
                continue
            task = asyncio.create_task(self._handle(run_id), name=f"run:{run_id}")
            self._active.add(task)
            task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task) -> None:
        self._active.discard(task)
        self._slots.release()
        if not task.cancelled() and task.exception() is not None:
            logger.error("run task failed", exc_info=task.exception())

    async def _reaper_loop(self) -> None:
        interval = get_builder_settings().RUN_REAPER_INTERVAL_SECONDS
        while not self._stopping:
            await asyncio.sleep(interval)
            with contextlib.suppress(Exception):
                await self.reap()
            with contextlib.suppress(Exception):
                from builder.quality.suite import sweep

                await sweep()

    async def _schedule_loop(self) -> None:
        from builder.schedules.service import fire_due

        interval = get_builder_settings().SCHEDULE_POLL_SECONDS
        while not self._stopping:
            try:
                await fire_due()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — e.g. DB briefly unreachable; try next tick
                logger.warning("schedule check failed; retrying", exc_info=True)
            await asyncio.sleep(interval)

    async def reap(self) -> int:
        stuck = await lease.stuck_run_ids()
        for run_id in stuck:
            await self.queue.enqueue(run_id)
        if stuck:
            logger.info("re-enqueued %d stuck run(s)", len(stuck))
        return len(stuck)

    # ── one run ──

    async def _handle(self, run_id: str) -> None:
        if not await lease.claim(run_id, self.worker_id):
            return  # someone else has it, or it's not runnable any more
        execution = asyncio.create_task(executor.execute(run_id, self.worker_id))
        heartbeat = asyncio.create_task(self._heartbeat(run_id, execution))
        try:
            await execution
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                # We are being stopped: stop the run too (it stays checkpointed).
                execution.cancel()
                raise
            # Only the execution was cancelled — by the heartbeat, on losing the
            # lease. Whoever holds it now (if anyone) continues; nothing to do.
            return
        finally:
            heartbeat.cancel()
            with contextlib.suppress(BaseException):
                await heartbeat
        # A test case's run: grade it now (the reaper's sweep catches any we miss).
        try:
            from builder.quality.suite import on_run_finished

            await on_run_finished(run_id)
        except Exception:  # noqa: BLE001 — grading must never take the worker down
            logger.warning("grading test run failed run=%s", run_id, exc_info=True)

    async def _heartbeat(self, run_id: str, execution: asyncio.Task) -> None:
        every = get_builder_settings().RUN_HEARTBEAT_SECONDS
        while not execution.done():
            await asyncio.sleep(every)
            try:
                still_mine = await lease.heartbeat(run_id, self.worker_id)
            except Exception:  # noqa: BLE001 — DB hiccup: keep going, the lease has slack
                logger.warning("heartbeat failed run=%s", run_id, exc_info=True)
                continue
            if not still_mine:
                logger.info("lost lease on run %s; stopping its execution", run_id)
                execution.cancel()
                return

    # ── tests / one-shot use ──

    async def drain(self, *, timeout: float = 30.0) -> None:
        """Process until the queue is empty and nothing is running (inline mode / tests)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            run_id = await self.queue.receive(timeout=0.05)
            if run_id is not None:
                await self._handle(run_id)
                continue
            if not self._active:
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("runs still in progress after drain timeout")


__all__ = ["Worker"]
