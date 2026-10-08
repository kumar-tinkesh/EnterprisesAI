"use client";

import { useEffect, useReducer, useRef, useState } from "react";

import { builderApi, runEventsUrl } from "@/lib/builder/api";
import { emptyRunView, isFinished, reduceRunEvent, type ApprovalsRefresh, type RunView } from "@/lib/builder/run-state";
import type { RunEvent } from "@/lib/builder/types";

type Action = { type: "reset"; runId: string | null } | { type: "event"; event: RunEvent | ApprovalsRefresh };

function reducer(view: RunView, action: Action): RunView {
  if (action.type === "reset") return { ...emptyRunView, runId: action.runId };
  return reduceRunEvent(view, action.event);
}

const POLL_MS = 3000;

/**
 * Live view of one run: WebSocket events after a snapshot. If the socket
 * can't be used (blocked, token expired -> 4401) it falls back to polling the
 * run, which goes through the normal request path (and its token refresh).
 */
export function useRunStream(runId: string | null, token: string): { view: RunView; live: boolean } {
  const [view, dispatch] = useReducer(reducer, emptyRunView);
  const [live, setLive] = useState(false);
  const finished = useRef(false);

  useEffect(() => {
    dispatch({ type: "reset", runId });
    finished.current = false;
    if (!runId || !token) return;

    let socket: WebSocket | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let closed = false;

    const refresh = async () => {
      try {
        // Only the approvals: status and steps belong to the live events, which may be newer.
        const run = await builderApi.getRun(token, runId);
        dispatch({ type: "event", event: { type: "approvals_refresh", approvals: run.approvals ?? [] } });
      } catch {
        /* the next event or poll catches up */
      }
    };

    const onEvent = (event: RunEvent) => {
      dispatch({ type: "event", event });
      // The event only names the approval; the run's snapshot carries what to show.
      if (event.type === "approval_requested") void refresh();
      if ((event.type === "snapshot" && isFinished(event.run.status)) || (event.type === "run_status" && isFinished(event.status))) {
        finished.current = true;
      }
    };

    const startPolling = () => {
      if (poll) return;
      const tick = async () => {
        try {
          const run = await builderApi.getRun(token, runId);
          onEvent({ type: "snapshot", run });
          if (isFinished(run.status) && poll) {
            clearInterval(poll);
            poll = null;
          }
        } catch {
          /* keep trying */
        }
      };
      void tick();
      poll = setInterval(tick, POLL_MS);
    };

    const open = () => {
      if (closed || finished.current) return;
      try {
        socket = new WebSocket(runEventsUrl(runId, token));
      } catch {
        startPolling();
        return;
      }
      socket.onopen = () => {
        attempts = 0;
        setLive(true);
      };
      socket.onmessage = (msg) => {
        try {
          onEvent(JSON.parse(msg.data) as RunEvent);
        } catch {
          /* ignore malformed */
        }
      };
      socket.onclose = (e) => {
        setLive(false);
        if (closed || finished.current) return;
        if (e.code === 4401 || e.code === 4404 || attempts >= 4) {
          startPolling();
          return;
        }
        attempts += 1;
        retry = setTimeout(open, Math.min(10_000, 1000 * 2 ** attempts));
      };
    };

    open();
    return () => {
      closed = true;
      socket?.close();
      if (poll) clearInterval(poll);
      if (retry) clearTimeout(retry);
      setLive(false);
    };
  }, [runId, token]);

  return { view, live };
}
