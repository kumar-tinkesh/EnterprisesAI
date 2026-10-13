"use client";

import { useCallback, useEffect, useMemo } from "react";
import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider, useReactFlow, type Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Bot } from "lucide-react";

import { nodeTypes, useNodeSizes, type StepNodeType } from "@/components/builder/step-node";
import { toolGraph } from "@/components/builder/tool-graph";
import type { ServerInfo } from "@/components/builder/agent-wizard/wizard-ui";
import { guardrailsOn } from "@/lib/builder/agent-wizard";
import type { RunView } from "@/lib/builder/run-state";
import type { DraftAgent, ToolCandidate } from "@/lib/builder/types";

/**
 * The agent being set up, drawn the way the editor will draw it: documents
 * on the left feeding the agent, tools on the right. It redraws on every
 * change in the panel, so each choice shows up here as it's made — and after
 * Create, a test run lights it up like the editor's canvas does.
 */
type PreviewProps = {
  draft: DraftAgent | null;
  generating: boolean;
  servers: Record<string, ServerInfo>;
  toolMeta: Record<string, ToolCandidate>;
  kbNames: Record<string, string>;
  profileLabel: string | null;
  runView: RunView;
  visible: boolean;
  /** Top-to-bottom layout for narrow screens: documents, then the agent, then its tools in two columns. */
  vertical: boolean;
  token: string;
  /** A node was clicked: the agent itself, or one of its tools or documents. */
  onOpen: (what: "agent" | "tool" | "knowledge") => void;
};

const COL = 270;
const ROW = 100;

/** Where each kind of node sits. Wide: documents | agent | tools, left to right. Narrow: top to bottom. */
function place(vertical: boolean, tools: number, kbs: number) {
  if (!vertical) {
    const tall = Math.max(tools, kbs, 1);
    return {
      agent: { x: 320, y: (tall - 1) * 55 },
      tool: (i: number) => ({ x: 680, y: i * 110 }),
      kb: (i: number) => ({ x: 0, y: i * 110 }),
    };
  }
  const centre = tools > 1 || kbs > 1 ? COL / 2 : 0;
  const grid = (count: number, top: number) => (i: number) => (count === 1 ? { x: centre, y: top } : { x: (i % 2) * COL, y: top + Math.floor(i / 2) * ROW });
  const agentY = kbs ? Math.ceil(kbs / 2) * ROW + 40 : 0;
  return { agent: { x: centre, y: agentY }, tool: grid(tools, agentY + ROW + 50), kb: grid(kbs, 0) };
}

export function WizardPreview(props: PreviewProps) {
  return (
    <ReactFlowProvider>
      <Preview {...props} />
    </ReactFlowProvider>
  );
}

function Preview({
  draft,
  generating,
  servers,
  toolMeta,
  kbNames,
  profileLabel,
  runView,
  visible,
  vertical,
  token,
  onOpen,
}: PreviewProps) {
  const flow = useReactFlow();
  const { sizes, track } = useNodeSizes();
  const toolIds = draft?.config.tool_ids ?? [];
  const kbIds = draft?.config.knowledge_base_ids ?? [];
  const active = runView.activeTool["agent"];
  const checks = guardrailsOn(draft?.config.guardrails).length;

  // agent → connector (connect it there, once) → its tools.
  const toolGraphFor = useCallback(
    (agent: { x: number; y: number }) =>
      toolGraph({
        toolIds,
        server: (sid) => {
          const s = servers[sid];
          const meta = Object.values(toolMeta).find((m) => m.server_id === sid);
          const name = (s && !s.loading && !s.missing ? s.name : meta?.server_name) ?? "Connector";
          return { name, connected: s && !s.loading && !s.missing ? s.connected : meta?.connected };
        },
        toolSubtitle: (tid) => (toolMeta[tid]?.risk ? `Risk: ${toolMeta[tid].risk}` : "A tool this agent may call"),
        active,
        usedTools: runView.usedTools,
        token,
        agent,
        vertical,
        ...(vertical ? { col: COL, row: ROW } : {}),
      }),
    [toolIds, servers, toolMeta, active, runView.usedTools, token, vertical],
  );

  const nodes: StepNodeType[] = useMemo(() => {
    if (!draft) {
      return generating
        ? [{ id: "agent", type: "step", position: { x: 0, y: 0 }, data: { type: "agent", title: "Designing your agent…", subtitle: "Reading your description", problems: [], state: "running" } }]
        : [];
    }
    const at = place(vertical, toolIds.length, kbIds.length);
    const detail = active ? `Calling ${active}…` : [profileLabel, checks ? `${checks} safety check${checks === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ") || null;
    const out: StepNodeType[] = [
      {
        id: "agent",
        type: "step",
        position: at.agent,
        data: { type: "agent", title: draft.name || "Your agent", subtitle: draft.goal || draft.role || "Give it a goal", problems: [], state: runView.steps["agent"], detail, vertical },
      },
    ];
    out.push(...toolGraphFor(at.agent).nodes);
    kbIds.forEach((kid, i) => {
      out.push({
        id: `kb:${kid}`,
        type: "step",
        position: at.kb(i),
        data: { type: "knowledge", title: kbNames[kid] ?? "Knowledge base", subtitle: "Searched when it needs facts", problems: [], vertical },
      });
    });
    return out.map((n) => (sizes[n.id] ? { ...n, measured: sizes[n.id] } : n));
  }, [draft, generating, toolIds, kbIds, kbNames, profileLabel, checks, runView, active, sizes, vertical, toolGraphFor]);

  const edges: Edge[] = useMemo(
    () => [
      ...toolGraphFor(place(vertical, toolIds.length, kbIds.length).agent).edges,
      ...kbIds.map((kid) => ({ id: `k:${kid}`, source: `kb:${kid}`, target: "agent", style: { stroke: "#c4b5fd", strokeDasharray: "4 4" } })),
    ],
    [toolGraphFor, toolIds.length, kbIds, vertical],
  );

  // Re-frame whenever something is added or removed, or the preview comes
  // back into view (phones switch between it and the setup panel).
  const shape = `${nodes.length}:${visible}:${vertical}`;
  useEffect(() => {
    if (!visible) return;
    const t = setTimeout(() => flow.fitView({ padding: 0.25, maxZoom: 1, duration: 250 }), 80);
    return () => clearTimeout(t);
  }, [shape, flow, visible]);

  return (
    <div className="relative h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={track}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={(_, n) => onOpen(n.id === "agent" ? "agent" : n.id.startsWith("kb:") ? "knowledge" : "tool")}
        deleteKeyCode={null}
        fitView
        fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#3f3f46" />
        <Controls showInteractive={false} />
      </ReactFlow>

      {!draft && !generating && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
          <Bot className="h-7 w-7 text-indigo-400" />
          <p className="text-sm font-medium text-zinc-300">Your agent will appear here</p>
          <p className="max-w-xs text-xs text-zinc-500">Describe it on the right. Every tool and document you add shows up on this canvas.</p>
        </div>
      )}

      {draft && (
        <ul className="pointer-events-none absolute left-3 top-3 flex flex-wrap gap-x-3 gap-y-1 rounded-lg bg-zinc-900/80 px-2.5 py-1.5 text-[11px] text-zinc-400" aria-label="Legend">
          <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-indigo-400" />Agent</li>
          <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-400" />Tool</li>
          <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-violet-400" />Documents</li>
          <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-red-400" />Needs connecting</li>
        </ul>
      )}
    </div>
  );
}
