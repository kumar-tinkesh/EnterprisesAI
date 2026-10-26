/**
 * "Arrange": tidy the canvas into columns, left to right.
 *
 * A step's column is its longest distance from a start (a step nothing leads
 * into), ignoring lines that loop back (a condition sending work round
 * again). Within a column, steps sit near the steps that lead into them, so
 * lines cross as little as a simple pass allows.
 */
import type { WorkflowEdge, WorkflowNode } from "@/lib/builder/types";

export const COLUMN_GAP = 340;
export const ROW_GAP = 160;

export function arrange(nodes: WorkflowNode[], edges: WorkflowEdge[]): WorkflowNode[] {
  const ids = new Set(nodes.map((n) => n.id));
  const out = new Map<string, string[]>();
  const into = new Map<string, string[]>();
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target) || e.source === e.target) continue;
    out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
    into.set(e.target, [...(into.get(e.target) ?? []), e.source]);
  }

  // Lines that close a loop (found by depth-first search from the starts) don't count.
  const back = new Set<string>();
  const state = new Map<string, "open" | "done">();
  const visit = (id: string) => {
    state.set(id, "open");
    for (const t of out.get(id) ?? []) {
      if (state.get(t) === "open") back.add(`${id}>${t}`);
      else if (!state.has(t)) visit(t);
    }
    state.set(id, "done");
  };
  const starts = nodes.filter((n) => !(into.get(n.id) ?? []).length).map((n) => n.id);
  for (const s of [...starts, ...nodes.map((n) => n.id)]) if (!state.has(s)) visit(s);

  const forwardInto = (id: string) => (into.get(id) ?? []).filter((p) => !back.has(`${p}>${id}`));
  const column = new Map<string, number>();
  const columnOf = (id: string, seen = new Set<string>()): number => {
    if (column.has(id)) return column.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const preds = forwardInto(id);
    const c = preds.length ? Math.max(...preds.map((p) => columnOf(p, seen) + 1)) : 0;
    column.set(id, c);
    return c;
  };
  nodes.forEach((n) => columnOf(n.id));

  const columns: string[][] = [];
  for (const n of nodes) (columns[column.get(n.id)!] ??= []).push(n.id);
  const row = new Map<string, number>();
  columns.forEach((col) => {
    // Order by where the steps leading in sit (keeps branches together); keep input order otherwise.
    const weight = (id: string) => {
      const preds = forwardInto(id).filter((p) => row.has(p));
      return preds.length ? preds.reduce((a, p) => a + row.get(p)!, 0) / preds.length : Number.MAX_SAFE_INTEGER;
    };
    col.sort((a, b) => weight(a) - weight(b));
    col.forEach((id, i) => row.set(id, i - (col.length - 1) / 2));
  });

  return nodes.map((n) => ({ ...n, position: { x: column.get(n.id)! * COLUMN_GAP, y: Math.round(row.get(n.id)! * ROW_GAP) } }));
}
