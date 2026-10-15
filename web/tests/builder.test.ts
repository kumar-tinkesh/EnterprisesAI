import { describe, expect, it } from "vitest";

import { connect, duplicateStep, forSave, insertAfter, newNode, overriddenParams, problemsByStep, removeSteps, stepTitle, toolName } from "@/lib/builder/graph";
import { displayTool, emptyRunView, isFinished, reduceRunEvent } from "@/lib/builder/run-state";
import type { Run, WorkflowEdge, WorkflowNode } from "@/lib/builder/types";

const nodes: WorkflowNode[] = [
  { id: "in", type: "input" },
  { id: "c", type: "condition" },
  { id: "a", type: "agent", agent_id: "ag1" },
  { id: "out", type: "output" },
];

describe("graph helpers", () => {
  it("lists each setting a step switched on", () => {
    expect(overriddenParams(null)).toEqual([]);
    expect(overriddenParams({ llm_model: "gpt-4.1-nano", llm: { temperature: 0.9, reasoning_effort: "high" }, tool_ids: [] })).toEqual([
      "llm_model", "llm.temperature", "llm.reasoning_effort", "tool_ids",
    ]);
  });

  it("copies a step below it, unconnected, but never the trigger", () => {
    const steps: WorkflowNode[] = [
      { id: "in", type: "input", position: { x: 0, y: 0 } },
      { id: "n1", type: "agent", agent_id: "ag1", label: "Writer", config_overrides: { llm: { temperature: 1 } }, position: { x: 300, y: 0 } },
    ];
    const copy = duplicateStep(steps, "n1")!;
    expect(copy.id).toBe("n2");
    expect(copy.label).toBe("Writer (copy)");
    expect(copy.agent_id).toBe("ag1");
    expect(copy.position!.y).toBeGreaterThan(0);
    copy.config_overrides!.llm = {};
    expect(steps[1].config_overrides).toEqual({ llm: { temperature: 1 } }); // a deep copy
    expect(duplicateStep(steps, "in")).toBeNull();
  });

  it("puts a Next step between a step and the one it led to, moving the rest right", () => {
    const steps: WorkflowNode[] = [
      { id: "in", type: "input", position: { x: 0, y: 0 } },
      { id: "a", type: "agent", position: { x: 330, y: 0 } },
      { id: "out", type: "output", position: { x: 660, y: 0 } },
    ];
    const lines: WorkflowEdge[] = [{ id: "e1", source: "in", target: "a" }, { id: "e2", source: "a", target: "out" }];
    const r = insertAfter(steps, lines, "a", "human_approval")!;
    expect(r.edges.map((e) => `${e.source}>${e.target}`).sort()).toEqual(["a>n1", "in>a", "n1>out"]);
    expect(r.nodes.find((n) => n.id === "n1")!.position).toEqual({ x: 660, y: 0 });
    expect(r.nodes.find((n) => n.id === "out")!.position).toEqual({ x: 990, y: 0 });
    // Branching out (two lines already) adds one more line instead.
    const forked = insertAfter(r.nodes, [...r.edges, { id: "e9", source: "a", target: "out" }], "a", "tool")!;
    expect(forked.edges.filter((e) => e.source === "a")).toHaveLength(3);
    expect(insertAfter(steps, lines, "out", "agent")).toBeNull();
  });

  it("labels lines out of a condition and refuses bad lines", () => {
    let edges: WorkflowEdge[] = [];
    edges = connect(nodes, edges, "in", "c");
    edges = connect(nodes, edges, "c", "a");
    edges = connect(nodes, edges, "c", "out");
    expect(edges.map((e) => e.condition ?? null)).toEqual([null, "Branch 1", "Branch 2"]);
    expect(connect(nodes, edges, "c", "a")).toBe(edges); // duplicate
    expect(connect(nodes, edges, "a", "in")).toBe(edges); // into the trigger
    expect(connect(nodes, edges, "out", "a")).toBe(edges); // out of the output
    expect(connect(nodes, edges, "a", "a")).toBe(edges); // to itself
  });

  it("never removes the trigger and drops the lines of removed steps", () => {
    const edges: WorkflowEdge[] = [
      { id: "e1", source: "in", target: "a" },
      { id: "e2", source: "a", target: "out" },
    ];
    const out = removeSteps(nodes, edges, ["in", "a"]);
    expect(out.nodes.map((n) => n.id)).toEqual(["in", "c", "out"]);
    expect(out.edges).toEqual([]);
  });

  it("creates new steps with unique ids and sensible defaults", () => {
    const step = newNode("agent", nodes, { x: 1, y: 2 });
    expect(step.id).toBe("n1");
    // Empty, so its panel offers an existing agent or a new one.
    expect(step.draft_agent).toBeUndefined();
    expect(step.agent_id).toBeUndefined();
    expect(newNode("human_approval", [...nodes, step], { x: 0, y: 0 }).id).toBe("n2");
  });

  it("titles steps from their label, agent or tool", () => {
    const agents = { ag1: { name: "Writer" } } as never;
    expect(stepTitle(nodes[2], agents)).toBe("Writer");
    expect(stepTitle({ id: "t", type: "tool", tool_id: "mcp:s1:send_email" }, {})).toBe("send_email");
    expect(stepTitle({ id: "t", type: "tool", label: "Notify" }, {})).toBe("Notify");
    expect(toolName("mcp:s1:a:b")).toBe("a:b");
  });

  it("groups problems by step", () => {
    const { byStep, general } = problemsByStep([
      { code: "x", message: "m1", node_id: "a" },
      { code: "y", message: "m2" },
    ]);
    expect(byStep.a[0].message).toBe("m1");
    expect(general).toHaveLength(1);
  });

  it("drops undefined keys before saving", () => {
    expect(forSave([{ id: "a", type: "agent", label: undefined }])).toEqual([{ id: "a", type: "agent" }]);
  });
});

describe("run view", () => {
  const snapshot: Run = {
    id: "r1", kind: "workflow", status: "running", name: "F", input: { text: "", variables: {} },
    output_text: null, output: null, error: null, prompt_tokens: null, completion_tokens: null, recoveries: 0, created_at: "",
    nodes: [
      { node_id: "a", node_type: "agent", attempt: 1, status: "failed", output_text: null, error: "x" },
      { node_id: "a", node_type: "agent", attempt: 2, status: "running", output_text: null, error: null },
    ],
    approvals: [
      { id: "p1", run_id: "r1", kind: "tool_call", node_id: "a", tool_name: "send", risk: "edit", status: "pending", payload: {}, created_at: "" },
      { id: "p0", run_id: "r1", kind: "tool_call", node_id: "a", tool_name: "send", risk: "edit", status: "approved", payload: {}, created_at: "" },
    ],
    tool_calls: [],
  };

  it("takes the latest attempt and only pending approvals from a snapshot", () => {
    const view = reduceRunEvent(emptyRunView, { type: "snapshot", run: snapshot });
    expect(view.steps.a).toBe("running");
    expect(view.approvals.map((a) => a.id)).toEqual(["p1"]);
  });

  it("an approvals refresh never overrides the live status", () => {
    let view = reduceRunEvent(emptyRunView, { type: "snapshot", run: snapshot });
    view = reduceRunEvent(view, { type: "run_status", status: "waiting" });
    view = reduceRunEvent(view, { type: "approvals_refresh", approvals: snapshot.approvals ?? [] });
    expect(view.status).toBe("waiting");
    expect(view.approvals.map((a) => a.id)).toEqual(["p1"]);
    expect(displayTool("demo__send_note")).toBe("send_note");
  });

  it("collects guardrail findings live and from a snapshot", () => {
    let view = reduceRunEvent(emptyRunView, { type: "guardrail", node_id: "a", rule: "pii_input", severity: "medium", message: "Hid 1 email" });
    expect(view.guardrails).toEqual([{ rule: "pii_input", severity: "medium", message: "Hid 1 email", node_id: "a" }]);
    expect(view.timeline.at(-1)).toMatchObject({ tone: "warn", text: "guardrail: Hid 1 email", nodeId: "a" });
    view = reduceRunEvent(view, {
      type: "snapshot",
      run: { ...snapshot, output: { text: null, guardrails: [{ rule: "injection_blocked", severity: "high", message: "Blocked" }] } },
    });
    expect(view.guardrails.map((g) => g.rule)).toEqual(["injection_blocked"]);
  });

  it("drops an approval once it's decided", () => {
    let view = reduceRunEvent(emptyRunView, { type: "snapshot", run: snapshot });
    view = reduceRunEvent(view, { type: "approval_resolved", approval_id: "p1", status: "approved" });
    expect(view.approvals).toEqual([]);
  });

  it("tracks steps, tools and the outcome from live events", () => {
    let view = reduceRunEvent(emptyRunView, { type: "snapshot", run: snapshot });
    view = reduceRunEvent(view, { type: "tool_call", node_id: "a", phase: "started", tool: "send_email", risk: "edit" });
    expect(view.activeTool.a).toBe("send_email");
    view = reduceRunEvent(view, { type: "tool_call", node_id: "a", phase: "finished", tool: "send_email", is_error: false });
    expect(view.activeTool.a).toBeNull();
    expect(view.usedTools).toContain("send_email");
    view = reduceRunEvent(view, { type: "node_status", node_id: "a", status: "succeeded" });
    view = reduceRunEvent(view, { type: "output", text: "done", sources: ["doc.pdf"] });
    view = reduceRunEvent(view, { type: "run_status", status: "succeeded" });
    expect(view.steps.a).toBe("succeeded");
    expect([view.output, view.sources, isFinished(view.status)]).toEqual(["done", ["doc.pdf"], true]);
    expect(view.timeline.at(-1)?.tone).toBe("ok");
  });
});
