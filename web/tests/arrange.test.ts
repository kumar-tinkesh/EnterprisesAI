import { describe, expect, it } from "vitest";

import { COLUMN_GAP, ROW_GAP, arrange } from "@/lib/builder/arrange";
import type { WorkflowEdge, WorkflowNode } from "@/lib/builder/types";

const n = (id: string, type: WorkflowNode["type"] = "agent"): WorkflowNode => ({ id, type, position: { x: 999, y: -42 } });
const e = (source: string, target: string): WorkflowEdge => ({ id: `${source}-${target}`, source, target });

describe("arrange", () => {
  it("lays a chain out left to right on one row", () => {
    const out = arrange([n("out", "output"), n("a"), n("in", "input")], [e("in", "a"), e("a", "out")]);
    const pos = Object.fromEntries(out.map((x) => [x.id, x.position]));
    expect(pos).toEqual({ in: { x: 0, y: 0 }, a: { x: COLUMN_GAP, y: 0 }, out: { x: 2 * COLUMN_GAP, y: 0 } });
  });

  it("puts parallel branches in one column and a join after the longest", () => {
    const out = arrange(
      [n("in", "input"), n("a"), n("b"), n("b2"), n("j", "join")],
      [e("in", "a"), e("in", "b"), e("b", "b2"), e("a", "j"), e("b2", "j")],
    );
    const pos = Object.fromEntries(out.map((x) => [x.id, x.position!])) as Record<string, { x: number; y: number }>;
    expect([pos.a.x, pos.b.x, pos.b2.x, pos.j.x]).toEqual([COLUMN_GAP, COLUMN_GAP, 2 * COLUMN_GAP, 3 * COLUMN_GAP]);
    expect(Math.abs(pos.a.y - pos.b.y)).toBe(ROW_GAP);
  });

  it("ignores a loop back to an earlier step", () => {
    const out = arrange([n("in", "input"), n("a"), n("c", "condition")], [e("in", "a"), e("a", "c"), e("c", "a")]);
    expect(out.map((x) => x.position!.x)).toEqual([0, COLUMN_GAP, 2 * COLUMN_GAP]);
  });
});
