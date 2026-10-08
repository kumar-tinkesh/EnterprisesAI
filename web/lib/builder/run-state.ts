/**
 * What the playground and the canvas show about a run, built from its
 * WebSocket events (a snapshot first, then live events). Pure — the
 * component only feeds events in.
 */

import type { Approval, Run, RunEvent, RunStatus } from "@/lib/builder/types";

export type StepState = "running" | "succeeded" | "failed" | "waiting" | "skipped";

export interface TimelineItem {
  key: string;
  tone: "info" | "ok" | "warn" | "error";
  /** For a step's event, shown after the step's name (the component knows the names). */
  text: string;
  nodeId?: string;
}

/** Fresh pending approvals for a run, without touching anything live events own. */
export type ApprovalsRefresh = { type: "approvals_refresh"; approvals: Approval[] };

/** "gmail__send_email" (the function name the model sees) -> "send_email". */
export function displayTool(name: string): string {
  const i = name.indexOf("__");
  return i >= 0 ? name.slice(i + 2) : name;
}

export interface RunView {
  runId: string | null;
  status: RunStatus | null;
  steps: Record<string, StepState>;
  /** Tool currently running per step (agent mode lights the tool's node). */
  activeTool: Record<string, string | null>;
  usedTools: string[];
  timeline: TimelineItem[];
  approvals: Approval[];
  output: string | null;
  sources: string[];
  error: string | null;
}

export const emptyRunView: RunView = {
  runId: null,
  status: null,
  steps: {},
  activeTool: {},
  usedTools: [],
  timeline: [],
  approvals: [],
  output: null,
  sources: [],
  error: null,
};

const TERMINAL: RunStatus[] = ["succeeded", "failed", "cancelled"];

export function isFinished(status: RunStatus | null): boolean {
  return status !== null && TERMINAL.includes(status);
}

function stepState(status: string): StepState | null {
  if (status === "running" || status === "succeeded" || status === "failed" || status === "waiting") return status;
  if (status === "skipped") return "skipped";
  return null;
}

function fromSnapshot(view: RunView, run: Run): RunView {
  const steps: Record<string, StepState> = {};
  // Latest attempt wins: the API lists node runs oldest first.
  for (const n of run.nodes ?? []) {
    const s = stepState(n.status);
    if (s) steps[n.node_id] = s;
  }
  return {
    ...view,
    runId: run.id,
    status: run.status,
    steps,
    approvals: (run.approvals ?? []).filter((a) => a.status === "pending"),
    usedTools: Array.from(new Set((run.tool_calls ?? []).map((c) => c.tool_name))),
    output: run.output_text ?? view.output,
    sources: run.output?.sources ?? view.sources,
    error: run.error,
  };
}

let seq = 0;
function add(view: RunView, item: Omit<TimelineItem, "key">): TimelineItem[] {
  seq += 1;
  return [...view.timeline, { ...item, key: `${Date.now()}-${seq}` }];
}

export function reduceRunEvent(view: RunView, event: RunEvent | ApprovalsRefresh): RunView {
  switch (event.type) {
    case "approvals_refresh":
      return { ...view, approvals: event.approvals.filter((a) => a.status === "pending") };
    case "snapshot":
      return fromSnapshot(view, event.run);
    case "ping":
      return view;
    case "approval_resolved":
      return { ...view, approvals: view.approvals.filter((a) => a.id !== event.approval_id) };
    case "run_status": {
      const tone = event.status === "failed" ? "error" : event.status === "succeeded" ? "ok" : event.status === "waiting" ? "warn" : "info";
      const text = event.status === "failed" && event.error ? `Run failed: ${event.error}` : `Run ${event.status}`;
      if (view.status === event.status) return view;
      // Pausing and resuming (waiting -> queued -> running) is visible on the badge; only the end is news.
      const timeline = isFinished(event.status) ? add(view, { tone, text }) : view.timeline;
      return { ...view, status: event.status, error: event.error ?? view.error, timeline };
    }
    case "node_status": {
      const s = stepState(event.status);
      if (!s) return view;
      const tone = s === "failed" ? "error" : s === "succeeded" ? "ok" : s === "waiting" ? "warn" : "info";
      const verb = { running: "started", succeeded: "finished", failed: "failed", waiting: "is waiting", skipped: "was skipped" }[s];
      const detail = s === "failed" && event.error ? `: ${event.error}` : "";
      return {
        ...view,
        steps: { ...view.steps, [event.node_id]: s },
        // A waiting step already said why ("is waiting for your decision").
        timeline: s === "waiting" ? view.timeline : add(view, { tone, text: `${verb}${detail}`, nodeId: event.node_id }),
      };
    }
    case "agent_turn":
      return event.tool_calls.length
        ? { ...view, timeline: add(view, { tone: "info", text: `decided to use ${event.tool_calls.map(displayTool).join(", ")}`, nodeId: event.node_id }) }
        : view;
    case "tool_call": {
      if (event.phase === "started") {
        return {
          ...view,
          activeTool: { ...view.activeTool, [event.node_id]: event.tool },
          timeline: add(view, { tone: "info", text: `calling ${event.tool}${event.risk && event.risk !== "read" ? ` (${event.risk})` : ""}`, nodeId: event.node_id }),
        };
      }
      const failed = event.phase === "finished" && event.is_error;
      return {
        ...view,
        activeTool: { ...view.activeTool, [event.node_id]: null },
        usedTools: Array.from(new Set([...view.usedTools, event.tool])),
        timeline: add(view, {
          tone: event.phase === "declined" ? "warn" : failed ? "error" : "ok",
          text: event.phase === "declined" ? `${event.tool} was declined` : failed ? `${event.tool} failed` : `${event.tool} done`,
          nodeId: event.node_id,
        }),
      };
    }
    case "condition":
      return { ...view, timeline: add(view, { tone: "info", text: `took the "${event.branch}" line`, nodeId: event.node_id }) };
    case "approval_requested":
      return { ...view, timeline: add(view, { tone: "warn", text: "is waiting for your decision", nodeId: event.node_id }) };
    case "output":
      return { ...view, output: event.text, sources: event.sources ?? [] };
    default:
      return view;
  }
}
