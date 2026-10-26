/**
 * What the playground and the canvas show about a run, built from its
 * WebSocket events (a snapshot first, then live events). Pure — the
 * component only feeds events in.
 */

import type { Approval, GuardrailFlag, Run, RunEvent, RunStatus } from "@/lib/builder/types";

export type StepState = "running" | "succeeded" | "failed" | "waiting" | "skipped";

export interface TimelineItem {
  key: string;
  tone: "info" | "ok" | "warn" | "error";
  /** For a step's event, shown after the step's name (the component knows the names). */
  text: string;
  nodeId?: string;
  /** Set when a sub-agent the step handed work to did this (its name). */
  via?: string;
  /** What went in or came out: a tool's input, a sub-agent's task, a result's start. */
  detail?: string;
}

/** Fresh pending approvals for a run, without touching anything live events own. */
export type ApprovalsRefresh = { type: "approvals_refresh"; approvals: Approval[] };

/** "gmail__send_email" (the function name the model sees) -> "send_email". */
export function displayTool(name: string): string {
  const i = name.indexOf("__");
  return i >= 0 ? name.slice(i + 2) : name;
}

/** A sub-agent's events carry its name in ``via`` (the step that asked it is the node). */
function viaOf(event: { via?: string }): { via?: string } {
  return event.via ? { via: event.via } : {};
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
  /** What the guardrails found or did, in order. */
  guardrails: GuardrailFlag[];
  /** Per sub-agent (by name): the tool it's calling now, and the tools it has used. */
  subActive: Record<string, string | null>;
  subUsed: Record<string, string[]>;
  /** The answer being written right now (streaming), until the real output arrives. */
  live: LiveText | null;
}

export interface LiveText {
  node: string;
  turn: number;
  text: string;
}

/**
 * Add a batch of streamed text. A batch must start where the text so far ends
 * (``at``); one starting at 0 begins the turn afresh (a new turn, or a retried
 * request), and one that doesn't fit — the viewer joined late — waits for a
 * fresh start rather than splicing a gap.
 */
export function addLive(live: LiveText | null, d: { node_id: string; turn: number; at: number; text: string }): LiveText | null {
  if (d.at === 0) return { node: d.node_id, turn: d.turn, text: d.text };
  if (live && live.node === d.node_id && live.turn === d.turn && live.text.length === d.at) return { ...live, text: live.text + d.text };
  return live;
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
  guardrails: [],
  subActive: {},
  subUsed: {},
  live: null,
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
    live: run.output_text || isFinished(run.status) ? null : view.live,
    guardrails: run.output?.guardrails ?? view.guardrails,
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
      // A turn that ends in tool calls wasn't the answer: its text makes way for the timeline.
      return event.tool_calls.length
        ? {
            ...view,
            timeline: add(view, { tone: "info", text: `decided to use ${event.tool_calls.map(displayTool).join(", ")}`, nodeId: event.node_id, ...viaOf(event) }),
            live: view.live?.node === event.node_id && !event.via ? null : view.live,
          }
        : view;
    case "tool_call": {
      const via = event.via;
      const tags = { nodeId: event.node_id, ...viaOf(event) };
      if (event.phase === "started") {
        const args = event.arguments ?? {};
        const detail = typeof args.task === "string" ? args.task : Object.keys(args).length ? JSON.stringify(args) : undefined;
        const item = add(view, { tone: "info", text: `calling ${event.tool}${event.risk && event.risk !== "read" ? ` (${event.risk})` : ""}`, detail, ...tags });
        // A sub-agent's tools light its own node, not the asking agent's tools.
        return via
          ? { ...view, subActive: { ...view.subActive, [via]: event.tool }, timeline: item }
          : { ...view, activeTool: { ...view.activeTool, [event.node_id]: event.tool }, timeline: item };
      }
      const failed = event.phase === "finished" && event.is_error;
      const timeline = add(view, {
        tone: event.phase === "declined" ? "warn" : failed ? "error" : "ok",
        text: event.phase === "declined" ? `${event.tool} was declined` : failed ? `${event.tool} failed` : `${event.tool} done`,
        detail: event.preview || undefined,
        ...tags,
      });
      return via
        ? {
            ...view,
            subActive: { ...view.subActive, [via]: null },
            subUsed: { ...view.subUsed, [via]: Array.from(new Set([...(view.subUsed[via] ?? []), event.tool])) },
            timeline,
          }
        : {
            ...view,
            activeTool: { ...view.activeTool, [event.node_id]: null },
            usedTools: Array.from(new Set([...view.usedTools, event.tool])),
            timeline,
          };
    }
    case "condition":
      return { ...view, timeline: add(view, { tone: "info", text: `took the "${event.branch}" line`, nodeId: event.node_id }) };
    case "approval_requested":
      return { ...view, timeline: add(view, { tone: "warn", text: "is waiting for your decision", nodeId: event.node_id }) };
    case "guardrail": {
      const flag: GuardrailFlag = { rule: event.rule, severity: event.severity, message: event.message, node_id: event.node_id };
      return {
        ...view,
        guardrails: [...view.guardrails, flag],
        timeline: add(view, { tone: event.severity === "high" ? "error" : "warn", text: `guardrail: ${event.message}`, nodeId: event.node_id }),
      };
    }
    case "output":
      return { ...view, output: event.text, sources: event.sources ?? [], live: null };
    case "output_delta":
      return { ...view, live: addLive(view.live, event) };
    default:
      return view;
  }
}
