/**
 * "Arrange": tidy the canvas into columns, left to right, and route skip-edges
 * cleanly around intermediate nodes so connections stay clearly visible.
 *
 * A step's column is its longest distance from a start (a step nothing leads
 * into), ignoring lines that loop back (a condition sending work round
 * again). Within a column, steps sit near their connected neighbours using
 * two barycenter sweeps so lines cross as little as possible.
 */
import type { WorkflowEdge, WorkflowNode } from "@/lib/builder/types";

export const COLUMN_GAP = 360;
export const ROW_GAP = 180;

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
  const forwardOut = (id: string) => (out.get(id) ?? []).filter((t) => !back.has(`${id}>${t}`));

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
  const assignCol = (col: string[]) => col.forEach((id, i) => row.set(id, i - (col.length - 1) / 2));

  // Pass 1: left-to-right based on incoming parents.
  columns.forEach((col) => {
    const order = new Map(col.map((id, i) => [id, i]));
    const weight = (id: string) => {
      const preds = forwardInto(id).filter((p) => row.has(p));
      return preds.length ? preds.reduce((a, p) => a + row.get(p)!, 0) / preds.length : Number.MAX_SAFE_INTEGER;
    };
    col.sort((a, b) => weight(a) - weight(b) || (order.get(a)! - order.get(b)!));
    assignCol(col);
  });

  // Pass 2 & 3: refine rows right-to-left then left-to-right considering both parents and children.
  const refineColumn = (col: string[]) => {
    if (col.length <= 1) return;
    const order = new Map(col.map((id, i) => [id, i]));
    const weight = (id: string) => {
      const neighbours = [...forwardInto(id), ...forwardOut(id)].filter((n) => row.has(n));
      return neighbours.length ? neighbours.reduce((a, n) => a + row.get(n)!, 0) / neighbours.length : row.get(id) ?? 0;
    };
    col.sort((a, b) => weight(a) - weight(b) || (order.get(a)! - order.get(b)!));
    assignCol(col);
  };
  for (let c = columns.length - 1; c >= 0; c--) refineColumn(columns[c]);
  for (let c = 0; c < columns.length; c++) refineColumn(columns[c]);

  return nodes.map((n) => ({ ...n, position: { x: column.get(n.id)! * COLUMN_GAP, y: Math.round(row.get(n.id)! * ROW_GAP) } }));
}

type LaneInterval = { minX: number; maxX: number; lane: number };

/**
 * Finds edges whose direct path passes across intermediate nodes and assigns each
 * a clean bypass rail Y coordinate (above or below the obstacle band) with lane staggering.
 */
export function computeEdgeDetours(nodes: WorkflowNode[], edges: WorkflowEdge[]): Record<string, number> {
  const detours: Record<string, number> = {};
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const topLanes: LaneInterval[] = [];
  const bottomLanes: LaneInterval[] = [];

  const nextLane = (lanes: LaneInterval[], minX: number, maxX: number): number => {
    const busy = new Set(lanes.filter((l) => !(l.maxX < minX || l.minX > maxX)).map((l) => l.lane));
    let lane = 0;
    while (busy.has(lane)) lane++;
    lanes.push({ minX, maxX, lane });
    return lane;
  };

  // Route shorter skip-edges closest to the nodes and longer ones on outer lanes.
  const candidates = edges
    .map((e) => {
      const src = byId.get(e.source);
      const tgt = byId.get(e.target);
      if (!src?.position || !tgt?.position) return null;
      const sx = src.position.x + 128;
      const tx = tgt.position.x + 48;
      return { edge: e, src, tgt, sx, sy: src.position.y + 40, tx, ty: tgt.position.y + 40, span: tx - sx };
    })
    .filter((item): item is NonNullable<typeof item> => !!item && item.span > 140)
    .sort((a, b) => a.span - b.span);

  for (const { edge, src, tgt, sx, sy, tx, ty } of candidates) {
    const minY = Math.min(sy, ty) - 44;
    const maxY = Math.max(sy, ty) + 44;

    const inSpan = nodes.filter((m) => {
      if (m.id === src.id || m.id === tgt.id || !m.position) return false;
      const mLeft = m.position.x + 16;
      const mRight = m.position.x + 160;
      return mLeft < tx - 16 && mRight > sx + 16;
    });

    const blocking = inSpan.filter((m) => {
      const my = m.position!.y;
      return my - 8 <= maxY && my + 132 >= minY;
    });
    if (!blocking.length) continue;

    const bandTop = Math.min(...inSpan.map((m) => m.position!.y), src.position!.y, tgt.position!.y);
    const bandBot = Math.max(...inSpan.map((m) => m.position!.y + 132), src.position!.y + 132, tgt.position!.y + 132);
    const mid = (sy + ty) / 2;
    const goTop = mid - bandTop <= bandBot - mid;

    if (goTop) {
      const lane = nextLane(topLanes, sx, tx);
      detours[edge.id] = Math.round(bandTop - 36 - lane * 26);
    } else {
      const lane = nextLane(bottomLanes, sx, tx);
      detours[edge.id] = Math.round(bandBot + 36 + lane * 26);
    }
  }

  return detours;
}
