/**
 * Pure helpers for the workflow canvas. The workflow's own nodes/edges are
 * the source of truth; React Flow's nodes are derived from them on render.
 */

import type { Agent, NodeType, Problem, WorkflowEdge, WorkflowNode } from "@/lib/builder/types";
import { describeSchedule } from "@/lib/builder/schedule";

/** Session-storage key for an AI draft handed from the studio to the editor. */
export const draftKey = (id: string) => `builder.draft.${id}`;
/** Set on a workflow made by "blank" / "with AI" until it's first saved; left unsaved, it's deleted on the way out. */
export const unsavedKey = (id: string) => `builder.unsaved-workflow.${id}`;

export const TRIGGERS: NodeType[] = ["input", "manual_trigger", "schedule_trigger"];

export const NODE_META: Record<NodeType, { title: string; hint: string; tone: string }> = {
  input: { title: "Input", hint: "Starts the workflow with a request and optional fields", tone: "sky" },
  manual_trigger: { title: "Manual trigger", hint: "Starts the workflow from a button", tone: "sky" },
  schedule_trigger: { title: "Schedule", hint: "Starts the workflow on a schedule", tone: "sky" },
  agent: { title: "Agent", hint: "Reasons, decides, uses tools and knowledge", tone: "indigo" },
  tool: { title: "Tool", hint: "One fixed action on a connected system", tone: "emerald" },
  condition: { title: "Condition", hint: "Takes one of its labelled lines", tone: "amber" },
  join: { title: "Join", hint: "Waits for parallel branches", tone: "violet" },
  human_approval: { title: "Approval", hint: "Waits for a person to approve", tone: "rose" },
  output: { title: "Output", hint: "Shapes the final answer", tone: "zinc" },
};

/** Steps the palette offers (a workflow has exactly one trigger, replaced not added). */
export const PALETTE: NodeType[] = ["agent", "tool", "condition", "join", "human_approval", "output"];

export function isTrigger(type: NodeType): boolean {
  return TRIGGERS.includes(type);
}

export function uniqueId(prefix: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  let n = 1;
  while (used.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

export function toolName(toolId: string | null | undefined): string {
  if (!toolId) return "";
  const parts = toolId.split(":");
  return parts.length >= 3 ? parts.slice(2).join(":") : toolId;
}

export function serverIdOf(toolId: string | null | undefined): string | null {
  if (!toolId) return null;
  const parts = toolId.split(":");
  return parts.length >= 3 && parts[0] === "mcp" ? parts[1] : null;
}

export function newNode(type: NodeType, nodes: WorkflowNode[], position: { x: number; y: number }): WorkflowNode {
  const id = uniqueId("n", nodes.map((n) => n.id));
  const node: WorkflowNode = { id, type, position };
  // An agent step starts empty: its panel offers an agent already made, or a new one.
  if (type === "human_approval") {
    node.approval_message = "Approve this before the workflow continues?";
  } else if (type === "join") {
    node.join_policy = { mode: "all" };
  } else if (type === "condition") {
    node.condition_config = { mode: "ai" };
  }
  return node;
}

export function stepTitle(node: WorkflowNode, agents: Record<string, Agent>): string {
  if (node.label) return node.label;
  if (node.type === "agent") {
    return node.draft_agent?.name || (node.agent_id && agents[node.agent_id]?.name) || "Agent";
  }
  if (node.type === "tool") return toolName(node.tool_id) || node.need || "Tool";
  return NODE_META[node.type].title;
}

export function stepSubtitle(node: WorkflowNode, agents: Record<string, Agent>): string {
  switch (node.type) {
    case "agent": {
      const a = node.draft_agent ?? (node.agent_id ? agents[node.agent_id] : undefined);
      return a ? a.goal : "Pick or create an agent";
    }
    case "tool":
      return node.tool_id ? node.need || "Calls a connected tool" : node.need ? `No tool yet: ${node.need}` : "Pick a tool";
    case "condition":
      return node.condition_config?.mode === "rule" ? "Rules decide the line" : "AI picks the line";
    case "join":
      return `Waits for ${node.join_policy?.mode ?? "all"} branches`;
    case "human_approval":
      return node.approval_message || "A person approves";
    case "output":
      return `Answer as ${node.output_config?.format ?? "markdown"}`;
    case "input":
      return node.variables?.length ? `${node.variables.length} field(s)` : "The request";
    case "schedule_trigger":
      return describeSchedule(node.schedule);
    default:
      return NODE_META[node.type].hint;
  }
}

/** A line between two steps. Lines out of a condition get a branch label. */
export function connect(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  source: string,
  target: string,
): WorkflowEdge[] {
  if (source === target) return edges;
  if (edges.some((e) => e.source === source && e.target === target)) return edges;
  const targetNode = nodes.find((n) => n.id === target);
  if (!targetNode || isTrigger(targetNode.type)) return edges;
  const sourceNode = nodes.find((n) => n.id === source);
  if (!sourceNode || sourceNode.type === "output") return edges;
  const edge: WorkflowEdge = { id: uniqueId("e", edges.map((e) => e.id)), source, target };
  if (sourceNode.type === "condition") {
    edge.condition = `Branch ${edges.filter((e) => e.source === source).length + 1}`;
  }
  return [...edges, edge];
}

/** Remove steps (never the trigger) and every line touching them. */
export function removeSteps(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  ids: string[],
): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
  const drop = new Set(ids.filter((id) => !isTrigger(nodes.find((n) => n.id === id)?.type ?? "agent")));
  return {
    nodes: nodes.filter((n) => !drop.has(n.id)),
    edges: edges.filter((e) => !drop.has(e.source) && !drop.has(e.target)),
  };
}

/** The settings a step's overrides switch on: "llm.temperature", "tool_ids", "llm_model", … */
export function overriddenParams(overrides: Record<string, unknown> | null | undefined): string[] {
  return Object.entries(overrides ?? {}).flatMap(([k, v]) =>
    v && typeof v === "object" && !Array.isArray(v) ? Object.keys(v).map((sub) => `${k}.${sub}`) : [k],
  );
}

/** Room one step takes on the canvas, with a gap (the cards are 270 wide). */
const STEP_W = 330;
const STEP_H = 200;

/** A copy of a step just below it, not yet connected. A trigger has no copy: a workflow has one. */
export function duplicateStep(nodes: WorkflowNode[], id: string): WorkflowNode | null {
  const src = nodes.find((n) => n.id === id);
  if (!src || isTrigger(src.type)) return null;
  const copy: WorkflowNode = structuredClone(src);
  copy.id = uniqueId("n", nodes.map((n) => n.id));
  copy.position = freeSpot(nodes, { x: (src.position?.x ?? 0) + 40, y: (src.position?.y ?? 0) + STEP_H });
  if (src.label) copy.label = `${src.label} (copy)`;
  return copy;
}

/** Whether a step can be followed by a one-tap "Next" (a condition's lines need a branch chosen). */
export function canAddAfter(type: NodeType): boolean {
  return type !== "output" && type !== "condition";
}

/**
 * A new step right after ``sourceId``. When that step leads to exactly one
 * other, the new one goes in between and everything after it moves right to
 * make room; otherwise it's added as one more line out of it.
 */
export function insertAfter(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  sourceId: string,
  type: NodeType,
): { nodes: WorkflowNode[]; edges: WorkflowEdge[]; id: string } | null {
  const src = nodes.find((n) => n.id === sourceId);
  if (!src || !canAddAfter(src.type) || isTrigger(type)) return null;
  const at = src.position ?? { x: 0, y: 0 };
  const out = edges.filter((e) => e.source === sourceId);
  const between = out.length === 1 && type !== "output";

  let placed = nodes;
  if (between) {
    const after = downstream(edges, out[0].target);
    after.delete(sourceId); // a loop back to the source keeps it where it is
    placed = nodes.map((n) => (after.has(n.id) ? { ...n, position: { x: (n.position?.x ?? 0) + STEP_W, y: n.position?.y ?? 0 } } : n));
  }
  const node = newNode(type, placed, between ? { x: at.x + STEP_W, y: at.y } : freeSpot(placed, { x: at.x + STEP_W, y: at.y }));
  const all = [...placed, node];
  let next = between ? edges.filter((e) => e.id !== out[0].id) : edges;
  next = connect(all, next, sourceId, node.id);
  if (between) next = connect(all, next, node.id, out[0].target);
  return { nodes: all, edges: next, id: node.id };
}

/** ``start`` and every step reachable from it. */
function downstream(edges: WorkflowEdge[], start: string): Set<string> {
  const seen = new Set([start]);
  const queue = [start];
  while (queue.length) {
    const id = queue.shift()!;
    for (const e of edges) {
      if (e.source === id && !seen.has(e.target)) {
        seen.add(e.target);
        queue.push(e.target);
      }
    }
  }
  return seen;
}

/** ``want``, or the nearest spot below it that no step covers. */
function freeSpot(nodes: WorkflowNode[], want: { x: number; y: number }): { x: number; y: number } {
  const taken = (p: { x: number; y: number }) =>
    nodes.some((n) => Math.abs((n.position?.x ?? 0) - p.x) < STEP_W - 40 && Math.abs((n.position?.y ?? 0) - p.y) < STEP_H - 10);
  let spot = want;
  for (let i = 0; i < 20 && taken(spot); i++) spot = { x: spot.x, y: spot.y + STEP_H };
  return spot;
}

export function updateStep(nodes: WorkflowNode[], id: string, patch: Partial<WorkflowNode>): WorkflowNode[] {
  return nodes.map((n) => (n.id === id ? { ...n, ...patch } : n));
}

export function problemsByStep(problems: Problem[]): { byStep: Record<string, Problem[]>; general: Problem[] } {
  const byStep: Record<string, Problem[]> = {};
  const general: Problem[] = [];
  for (const p of problems) {
    if (p.node_id) (byStep[p.node_id] ??= []).push(p);
    else general.push(p);
  }
  return { byStep, general };
}

/** Required inputs the person must fill in before running. */
export function inputFields(nodes: WorkflowNode[]) {
  return nodes.find((n) => n.type === "input")?.variables ?? [];
}

/** Strip canvas-only details before sending a graph to the backend. */
export function forSave(nodes: WorkflowNode[]): WorkflowNode[] {
  return nodes.map((n) => {
    const out: WorkflowNode = { ...n };
    for (const key of Object.keys(out) as (keyof WorkflowNode)[]) {
      if (out[key] === undefined) delete out[key];
    }
    return out;
  });
}
