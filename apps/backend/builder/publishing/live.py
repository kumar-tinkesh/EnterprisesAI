"""A published run, live, for whoever started it: Server-Sent Events.

    event: run     {...the caller's view of the run}   first, then whenever its state changes
    event: delta   {"turn": 2, "at": 0, "text": "..."} the answer as it's written (runs started with stream on)

Only what a caller may see goes out — the same view as polling (refreshed as
each step starts and ends), plus the answer's text while it's being written.
Tool calls, their arguments and results never do, nor what a step produced
beyond the view's own step list. The stream ends after the event
that shows the run finished. ``at`` is where ``text`` starts in that turn's
answer: a caller who isn't exactly there (joined late, or the model request
was retried and started over at 0) should start that turn's text fresh.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Awaitable, Callable

from builder.runs import states
from builder.runs.events import get_event_bus

# Events that change what the caller's view shows.
_STATE_EVENTS = {"run_status", "node_status", "approval_requested", "approval_resolved", "output"}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def caller_events(run_id: str, view: Callable[[], Awaitable[dict]], *, idle_seconds: float = 15.0) -> AsyncIterator[str]:
    """``view()``: the caller's view of the run, read fresh each time."""
    # Subscribed before the first view, so nothing in between is missed.
    async with get_event_bus().subscribe(run_id) as subscription:
        current = await view()
        yield _sse("run", current)
        if current["status"] in states.TERMINAL:
            return
        while True:
            event = await subscription.get(timeout=idle_seconds)
            if event is None:
                current = await view()  # a missed event can't leave a finished run hanging open
                if current["status"] in states.TERMINAL:
                    yield _sse("run", current)
                    return
                yield ": ping\n\n"
                continue
            kind = event.get("type")
            if kind == "output_delta":
                yield _sse("delta", {"turn": event.get("turn"), "at": event.get("at"), "text": event.get("text") or ""})
            elif kind in _STATE_EVENTS:
                current = await view()
                yield _sse("run", current)
                if current["status"] in states.TERMINAL:
                    return


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

__all__ = ["caller_events", "SSE_HEADERS"]
