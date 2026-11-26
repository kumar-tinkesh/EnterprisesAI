import { MarkerType, type Edge } from "@xyflow/react";

import type { StepNodeType } from "@/components/builder/step-node";
import { groupByServer } from "@/lib/builder/agent-wizard";
import { toolName } from "@/lib/builder/graph";

type XY = { x: number; y: number };

/** What the canvas knows about a connector; ``connected`` is undefined while it's still loading. */
export type GraphServer = { name: string; connected?: boolean };

/**
 * The agent's tools on the canvas, grouped under their connector:
 * agent → connector (connect it here, once) → each of its tools.
 * Tools whose connector is unknown hang off the agent directly.
 *
 * Wide: connectors in one column right of the agent, their tools in the next.
 * Vertical: connectors in a row under the agent, each one's tools stacked below it.
 */
export function toolGraph({
  toolIds,
  server,
  toolSubtitle,
  active,
  usedTools,
  token,
  agent,
  vertical = false,
  col = 340,
  row = 128,
  at = (_key, fallback) => fallback,
}: {
  toolIds: string[];
  server: (serverId: string) => GraphServer | undefined;
  toolSubtitle: (toolId: string) => string;
  active?: string | null;
  usedTools: string[];
  token: string;
  /** Where the agent node sits. */
  agent: XY;
  vertical?: boolean;
  col?: number;
  row?: number;
  /** A position the person dragged a node to, else ``fallback``. */
  at?: (key: string, fallback: XY) => XY;
}): { nodes: StepNodeType[]; edges: Edge[] } {
  const nodes: StepNodeType[] = [];
  const edges: Edge[] = [];
  const line = (on: boolean, done = false) => ({
    type: "smoothstep" as const,
    animated: on,
    markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color: on ? "#38bdf8" : done ? "#34d399" : "#6366f1" },
    style: { stroke: on ? "#38bdf8" : done ? "#34d399" : "#6366f1", strokeWidth: on ? 2.5 : 1.75, opacity: on || done ? 1 : 0.78 },
  });
  const groups = groupByServer(toolIds);
  let slot = 0; // tool rows used so far (wide layout)

  groups.forEach((g, gi) => {
    const known = g.serverId !== "unknown" ? server(g.serverId) : undefined;
    const names = g.toolIds.map(toolName);
    const groupOn = !!active && names.includes(active);
    const groupUsed = names.some((n) => usedTools.includes(n));
    const toolPos = (j: number): XY =>
      vertical
        ? { x: agent.x + (gi - (groups.length - 1) / 2) * col, y: agent.y + row * (known ? 2 : 1) + j * row }
        : { x: agent.x + col * (known ? 2 : 1), y: (slot + j) * row };

    let parent = "agent";
    if (known) {
      const needsConnecting = known.connected === false;
      const sid = `server:${g.serverId}`;
      const fallback = vertical
        ? { x: toolPos(0).x, y: agent.y + row }
        : { x: agent.x + col, y: ((slot + slot + g.toolIds.length - 1) / 2) * row };
      nodes.push({
        id: sid,
        type: "step",
        position: at(sid, fallback),
        data: {
          vertical,
          type: "server",
          title: known.name,
          serverName: known.name,
          subtitle: known.connected === undefined ? "Checking connection…" : needsConnecting ? "Not connected yet" : `Connected · ${g.toolIds.length} tool${g.toolIds.length === 1 ? "" : "s"}`,
          problems: needsConnecting ? [{ code: "not_connected", message: `Connect ${known.name} before it can run.` }] : [],
          connect: needsConnecting ? { serverId: g.serverId, serverName: known.name, token } : undefined,
          state: groupOn ? "running" : groupUsed ? "succeeded" : undefined,
        },
      });
      edges.push({ id: `e:${sid}`, source: "agent", target: sid, ...line(groupOn, groupUsed) });
      parent = sid;
    }

    g.toolIds.forEach((tid, j) => {
      const name = toolName(tid);
      const id = `tool:${tid}`;
      const isUsed = usedTools.includes(name);
      nodes.push({
        id,
        type: "step",
        position: at(id, toolPos(j)),
        data: {
          vertical,
          type: "tool",
          title: name,
          serverName: known?.name,
          subtitle: toolSubtitle(tid),
          problems: [],
          state: active === name ? "running" : isUsed ? "succeeded" : undefined,
        },
      });
      edges.push({ id: `e:${tid}`, source: parent, target: id, ...line(active === name, isUsed) });
    });
    slot += g.toolIds.length;
  });

  return { nodes, edges };
}
