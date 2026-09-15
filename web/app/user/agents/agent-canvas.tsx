"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Bot, CheckCircle2, Send, Server, Link2 } from "lucide-react";

import {
  vendorApi,
  ApiError,
  type ToolSearchResponse,
  type ToolCallPlanResponse,
  type ToolSearchResult,
  type MCPServerEntry,
} from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

// ─── Node data shapes ───────────────────────────────────────────────────────
type OrchestratorNodeData = { loading: boolean; query: string };
type ToolNodeData = {
  tool: ToolSearchResult;
  selected: boolean;
  planArguments: Record<string, unknown> | null;
};
type BlockedNodeData = {
  server: MCPServerEntry | undefined;
  serverId: string;
  onConnect: (serverId: string) => void;
};

// ─── Custom node components ─────────────────────────────────────────────────
function OrchestratorNode({ data }: NodeProps<Node<OrchestratorNodeData>>) {
  return (
    <div className="w-44 rounded-lg border border-indigo-400/40 bg-indigo-500/10 p-3 text-white backdrop-blur-sm">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <Bot className="h-3.5 w-3.5" /> Orchestrator
      </div>
      <p className="mt-1 line-clamp-3 text-[10px] text-indigo-200">
        {data.loading
          ? "Thinking…"
          : data.query
            ? `"${data.query}"`
            : "Waiting for a request"}
      </p>
      {data.loading && (
        <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/10">
          <div className="h-full w-full animate-pulse rounded-full bg-white/50" />
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!border-0 !bg-indigo-300" />
    </div>
  );
}

function ToolNode({ data }: NodeProps<Node<ToolNodeData>>) {
  const { tool, selected, planArguments } = data;
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={cn(
        "nodrag w-48 cursor-default rounded-lg border p-2.5 backdrop-blur-sm transition-all",
        selected ? "border-emerald-400/60 bg-emerald-500/10 ring-1 ring-emerald-400/30" : "border-white/15 bg-white/5"
      )}
      onClick={() => selected && planArguments && setExpanded((e) => !e)}
    >
      <Handle type="target" position={Position.Left} className="!border-0 !bg-zinc-400" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[11px] font-semibold text-zinc-100">
          {tool.tool_name}
        </span>
        {tool.score != null && (
          <span className="shrink-0 rounded bg-white/10 px-1 py-0.5 font-mono text-[9px] text-zinc-300">
            {tool.score.toFixed(2)}
          </span>
        )}
      </div>
      <span className="mt-1 inline-block rounded bg-sky-500/15 px-1 py-0.5 font-mono text-[9px] text-sky-300">
        {tool.server_name}
      </span>
      {selected && (
        <div className="mt-1.5 flex items-center gap-1 text-[9px] font-medium text-emerald-300">
          <CheckCircle2 className="h-2.5 w-2.5" /> Selected by orchestrator
        </div>
      )}
      {selected && expanded && planArguments && (
        <pre className="mt-1.5 max-h-28 overflow-auto rounded bg-black/30 p-1.5 text-[9px] text-zinc-300">
          {JSON.stringify(planArguments, null, 2)}
        </pre>
      )}
    </div>
  );
}

function BlockedServerNode({ data }: NodeProps<Node<BlockedNodeData>>) {
  return (
    <div className="w-48 rounded-lg border border-amber-400/30 bg-amber-500/10 p-2.5 backdrop-blur-sm">
      <Handle type="target" position={Position.Left} className="!border-0 !bg-amber-400" />
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-200">
        <Server className="h-3 w-3" /> {data.server?.name ?? data.serverId}
      </div>
      <p className="mt-1 text-[9px] text-amber-300/80">Not connected yet — best match is here.</p>
      <button
        type="button"
        className="nodrag mt-1.5 inline-flex items-center gap-1 rounded-md border border-amber-400/40 bg-amber-500/10 px-1.5 py-1 text-[9px] font-medium text-amber-200 hover:bg-amber-500/20 cursor-pointer"
        onClick={() => data.onConnect(data.serverId)}
      >
        <Link2 className="h-2.5 w-2.5" /> Connect
      </button>
    </div>
  );
}

const nodeTypes = {
  orchestrator: OrchestratorNode,
  tool: ToolNode,
  blocked: BlockedServerNode,
};

// ─── Graph builder (pure) ───────────────────────────────────────────────────
function buildGraph(
  query: string,
  loading: boolean,
  searchResult: ToolSearchResponse | null,
  planResult: ToolCallPlanResponse | null,
  serverById: Record<string, MCPServerEntry>,
  onConnect: (serverId: string) => void
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [
    {
      id: "orchestrator",
      type: "orchestrator",
      position: { x: 20, y: 200 },
      data: { loading, query } satisfies OrchestratorNodeData,
      draggable: false,
      hidden: true,
    },
  ];
  const edges: Edge[] = [];

  const results = searchResult?.results ?? [];
  const blockedIds = searchResult?.needs_connection_server_ids ?? [];
  const selectedToolId = planResult?.plan?.tool_id ?? null;

  let y = 0;
  for (const tool of results) {
    const id = `tool-${tool.tool_id}`;
    const selected = tool.tool_id === selectedToolId;
    nodes.push({
      id,
      type: "tool",
      position: { x: 320, y },
      data: {
        tool,
        selected,
        planArguments: selected ? (planResult?.plan?.arguments ?? null) : null,
      } satisfies ToolNodeData,
      draggable: false,
    });
    edges.push({
      id: `e-${id}`,
      source: "orchestrator",
      target: id,
      animated: selected,
      style: selected
        ? { stroke: "#10b981", strokeWidth: 2.5 }
        : { stroke: "#c4c4cc", strokeWidth: 1.5, strokeDasharray: "4 4" },
    });
    y += 100;
  }

  for (const serverId of blockedIds) {
    const id = `blocked-${serverId}`;
    nodes.push({
      id,
      type: "blocked",
      position: { x: 320, y },
      data: { server: serverById[serverId], serverId, onConnect } satisfies BlockedNodeData,
      draggable: false,
    });
    edges.push({
      id: `e-${id}`,
      source: "orchestrator",
      target: id,
      style: { stroke: "#f59e0b", strokeWidth: 1.5, strokeDasharray: "4 4" },
    });
    y += 100;
  }

  return { nodes, edges };
}

// ─── Main component ─────────────────────────────────────────────────────────
export default function AgentCanvasBuilder({
  serverById,
  onConnect,
  hasAnyConnectedServer,
  onScrollToCatalog,
}: {
  serverById: Record<string, MCPServerEntry>;
  onConnect: (serverId: string) => void;
  hasAnyConnectedServer: boolean;
  onScrollToCatalog: () => void;
}) {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [searchResult, setSearchResult] = useState<ToolSearchResponse | null>(null);
  const [planResult, setPlanResult] = useState<ToolCallPlanResponse | null>(null);

  const searchMutation = useMutation({
    mutationFn: (q: string) =>
      vendorApi.searchCatalogTools(accessToken, { q, top_k_servers: 5, top_k_tools: 8 }),
    onSuccess: setSearchResult,
  });
  const planMutation = useMutation({
    mutationFn: (q: string) =>
      vendorApi.planToolCall(accessToken, { q, top_k_servers: 5, top_k_tools: 8 }),
    onSuccess: setPlanResult,
  });

  const isLoading = searchMutation.isPending || planMutation.isPending;
  const error =
    (searchMutation.isError &&
      (searchMutation.error instanceof ApiError ? searchMutation.error.message : "Search failed")) ||
    (planMutation.isError &&
      (planMutation.error instanceof ApiError ? planMutation.error.message : "Plan failed")) ||
    null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setSubmittedQuery(q);
    setSearchResult(null);
    setPlanResult(null);
    searchMutation.mutate(q);
    planMutation.mutate(q);
  };

  const { nodes, edges } = useMemo(
    () => buildGraph(submittedQuery, isLoading, searchResult, planResult, serverById, onConnect),
    [submittedQuery, isLoading, searchResult, planResult, serverById, onConnect]
  );

  return (
    <div className="flex h-screen w-full flex-col">
      {!hasAnyConnectedServer && (
        <div className="absolute left-1/2 top-16 z-10 flex -translate-x-1/2 items-center gap-3 rounded-md border border-amber-400/30 bg-amber-500/10 px-3 py-2 backdrop-blur-sm">
          <p className="text-xs text-amber-200">
            You haven&apos;t connected any MCP server yet.
          </p>
          <button
            type="button"
            onClick={onScrollToCatalog}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-400/40 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-200 hover:bg-amber-500/20 cursor-pointer"
          >
            <Link2 className="h-3 w-3" /> Connect a server
          </button>
        </div>
      )}

      <div className="relative flex-1 bg-zinc-950">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.3 }}
            nodesConnectable={false}
            colorMode="dark"
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} color="#3f3f46" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </ReactFlowProvider>
      </div>

      {error && <p className="bg-zinc-950 px-6 pt-3 text-xs text-red-400">{error}</p>}

      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 border-t border-white/10 bg-zinc-950 p-4"
      >
        <Input
          placeholder="Describe what you want to do…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="border-white/10 bg-white/5 text-zinc-100 placeholder:text-zinc-500 focus-visible:ring-indigo-500"
        />
        <button
          type="submit"
          disabled={isLoading || !query.trim()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 cursor-pointer"
        >
          {isLoading ? <Spinner className="h-4 w-4" /> : <Send className="h-4 w-4" />}
          Send
        </button>
      </form>
    </div>
  );
}
