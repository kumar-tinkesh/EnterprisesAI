"use client";

import { createContext, memo, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle, BookOpen, Bot, CalendarClock, CheckCircle2, CircleDot, GitBranch, Hand, Link2, Loader2, LogIn, Merge,
  PlayCircle, Send, Wrench, XCircle,
} from "lucide-react";

import { builderApi } from "@/lib/builder/api";
import { serverIdOf, toolName } from "@/lib/builder/graph";
import type { StepState } from "@/lib/builder/run-state";
import { describeSchedule } from "@/lib/builder/schedule";
import type { Agent, NodeType, Problem, WorkflowEdge, WorkflowNode } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** What the canvas shares with its nodes (so node cards can edit in place). */
export interface CanvasCtx {
  token: string;
  readOnly: boolean;
  agents: Record<string, Agent>;
  edges: WorkflowEdge[];
  inputText: string;
  setInputText: (text: string) => void;
  patch: (nodeId: string, patch: Partial<WorkflowNode>) => void;
  open: (nodeId: string) => void;
}
export const CanvasContext = createContext<CanvasCtx | null>(null);

export type FlowNodeData = {
  node: WorkflowNode;
  title: string;
  problems: Problem[];
  state?: StepState;
  detail?: string | null;
  /** The step's output from the last run on the canvas. */
  output?: string | null;
};
export type FlowNodeType = Node<FlowNodeData, "flow">;

const LOOK: Record<NodeType, { label: string; hint: string; Icon: typeof Bot; head: string }> = {
  input: { label: "Input", hint: "Entry point for workflow run", Icon: LogIn, head: "from-sky-500 to-blue-600" },
  manual_trigger: { label: "Manual Trigger", hint: "Starts when Run is clicked", Icon: PlayCircle, head: "from-sky-500 to-blue-600" },
  schedule_trigger: { label: "Schedule Trigger", hint: "Starts on a schedule", Icon: CalendarClock, head: "from-sky-500 to-cyan-600" },
  agent: { label: "Agent", hint: "AI agent performs processing", Icon: Bot, head: "from-violet-600 to-purple-600" },
  tool: { label: "Tool Call", hint: "Calls one tool of a connector", Icon: Wrench, head: "from-zinc-600 to-zinc-700" },
  condition: { label: "Condition", hint: "Branches logic", Icon: GitBranch, head: "from-amber-500 to-orange-600" },
  join: { label: "Join", hint: "Waits for parallel branches", Icon: Merge, head: "from-fuchsia-600 to-violet-700" },
  human_approval: { label: "Human Approval", hint: "Pauses for a person to approve", Icon: Hand, head: "from-rose-500 to-pink-600" },
  output: { label: "Output", hint: "Final answer", Icon: Send, head: "from-emerald-500 to-teal-600" },
};
export const NODE_LOOK = LOOK;

const RING: Record<StepState, string> = {
  running: "ring-2 ring-sky-400 shadow-[0_0_24px_rgba(56,189,248,0.35)]",
  succeeded: "ring-2 ring-emerald-400",
  failed: "ring-2 ring-red-500",
  waiting: "ring-2 ring-amber-400 animate-pulse",
  skipped: "opacity-50",
};
const NO_INPUT: NodeType[] = ["input", "manual_trigger", "schedule_trigger"];

function StateIcon({ state }: { state?: StepState }) {
  if (state === "running") return <Loader2 className="h-4 w-4 animate-spin text-white" aria-label="Running" />;
  if (state === "succeeded") return <CheckCircle2 className="h-4 w-4 text-white" aria-label="Done" />;
  if (state === "failed") return <XCircle className="h-4 w-4 text-white" aria-label="Failed" />;
  if (state === "waiting") return <CircleDot className="h-4 w-4 text-white" aria-label="Waiting for you" />;
  return null;
}

function Chip({ children, tone = "zinc", title }: { children: React.ReactNode; tone?: "zinc" | "emerald" | "amber" | "violet" | "sky"; title?: string }) {
  const tones = {
    zinc: "border-white/10 bg-white/5 text-zinc-300",
    emerald: "border-emerald-400/30 bg-emerald-500/10 text-emerald-300",
    amber: "border-amber-400/30 bg-amber-500/10 text-amber-300",
    violet: "border-violet-400/30 bg-violet-500/10 text-violet-200",
    sky: "border-sky-400/30 bg-sky-500/10 text-sky-300",
  };
  return <span title={title} className={cn("inline-flex max-w-full items-center gap-1 truncate rounded-md border px-1.5 py-0.5 text-[11px]", tones[tone])}>{children}</span>;
}

function ToolBody({ node, ctx }: { node: WorkflowNode; ctx: CanvasCtx }) {
  const serverId = serverIdOf(node.tool_id);
  const server = useQuery({
    queryKey: ["builder-server-tools", serverId],
    queryFn: () => builderApi.serverTools(ctx.token, serverId!),
    enabled: !!ctx.token && !!serverId,
    staleTime: 60_000,
  });
  if (!node.tool_id) {
    return (
      <button type="button" onClick={() => ctx.open(node.id)} className="nodrag w-full rounded-lg border border-dashed border-white/15 px-2 py-2 text-left text-xs text-zinc-400 hover:border-indigo-400/60 hover:text-zinc-200 cursor-pointer">
        {node.need ? <>Needs a tool: <span className="text-zinc-200">{node.need}</span></> : "Pick a tool"}
      </button>
    );
  }
  const pinned = Object.keys(node.tool_args ?? {}).length;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {server.data ? (
          server.data.connected ? (
            <Chip tone="emerald"><CheckCircle2 className="h-3 w-3" /> {server.data.server_name}</Chip>
          ) : (
            <a href="/user/agents" className="nodrag" title="Connect your account on the AI Compiler page">
              <Chip tone="amber"><Link2 className="h-3 w-3" /> Connect {server.data.server_name}</Chip>
            </a>
          )
        ) : (
          <Chip>…</Chip>
        )}
        {server.data && <Chip><Wrench className="h-3 w-3" /> {server.data.tools.length} Tools</Chip>}
      </div>
      <select
        aria-label="Tool"
        className="nodrag w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-zinc-100 focus:border-indigo-400 focus:outline-none"
        value={toolName(node.tool_id)}
        disabled={ctx.readOnly || !server.data}
        onChange={(e) => ctx.patch(node.id, { tool_id: `mcp:${serverId}:${e.target.value}`, tool_args: null })}
      >
        {!server.data && <option>{toolName(node.tool_id)}</option>}
        {server.data?.tools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
      </select>
      <div className="flex flex-wrap gap-x-3 text-[11px]">
        <button type="button" className="nodrag text-indigo-300 hover:text-indigo-200 cursor-pointer" onClick={() => ctx.open(node.id)}>
          {pinned ? `${pinned} pinned value${pinned === 1 ? "" : "s"}` : "+ Pin a fixed value"}
        </button>
        <button type="button" className="nodrag text-zinc-400 underline hover:text-zinc-200 cursor-pointer" onClick={() => ctx.open(node.id)}>
          {node.message_template ? "Custom message set" : "Advanced: custom message"}
        </button>
      </div>
    </div>
  );
}

function Body({ node, ctx }: { node: WorkflowNode; ctx: CanvasCtx }) {
  switch (node.type) {
    case "input":
      return (
        <div>
          <p className="mb-1.5 text-center text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Start trigger query</p>
          <textarea
            aria-label="Start trigger query"
            className="nodrag nowheel h-16 w-full resize-none rounded-lg border border-white/10 bg-white/5 px-2.5 py-2 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-indigo-400 focus:outline-none"
            placeholder="Enter prompt or input text to start run…"
            value={ctx.inputText}
            onChange={(e) => ctx.setInputText(e.target.value)}
          />
          {(node.variables ?? []).length > 0 && <p className="mt-1 text-[10.5px] text-zinc-500">+ {(node.variables ?? []).length} input field(s)</p>}
        </div>
      );
    case "manual_trigger":
      return <p className="text-xs text-zinc-400">Starts when you press Run.</p>;
    case "schedule_trigger":
      return <Chip tone="sky"><CalendarClock className="h-3 w-3" /> {describeSchedule(node.schedule)}</Chip>;
    case "agent": {
      const a = node.draft_agent ?? (node.agent_id ? ctx.agents[node.agent_id] : undefined);
      if (!a) {
        return (
          <button type="button" onClick={() => ctx.open(node.id)} className="nodrag w-full rounded-lg border border-dashed border-white/15 px-2 py-2 text-left text-xs text-zinc-400 hover:border-indigo-400/60 hover:text-zinc-200 cursor-pointer">
            Set up the agent for this step
          </button>
        );
      }
      const tools = a.config?.tool_ids?.length ?? 0;
      const kbs = a.config?.knowledge_base_ids?.length ?? 0;
      const overrides = Object.keys(node.config_overrides ?? {}).length;
      return (
        <div className="flex flex-wrap gap-1.5">
          <Chip><span className="font-mono">{a.llm_model || "default model"}</span></Chip>
          {tools > 0 && <Chip tone="violet"><Wrench className="h-3 w-3" /> {tools}</Chip>}
          {kbs > 0 && <Chip tone="sky"><BookOpen className="h-3 w-3" /> {kbs}</Chip>}
          {node.draft_agent && <Chip tone="amber">{node.agent_id ? "customized" : "new — saved with the workflow"}</Chip>}
          {overrides > 0 && <Chip tone="amber">{overrides} step override{overrides === 1 ? "" : "s"}</Chip>}
        </div>
      );
    }
    case "tool":
      return <ToolBody node={node} ctx={ctx} />;
    case "condition": {
      const outs = ctx.edges.filter((e) => e.source === node.id).map((e) => e.condition).filter(Boolean);
      return (
        <div className="space-y-1.5">
          <p className="text-xs text-zinc-400">{node.condition_config?.mode === "rule" ? "Rules decide" : "AI decides"} the line</p>
          <div className="flex flex-wrap gap-1">{outs.map((o) => <Chip key={o} tone="amber">{o}</Chip>)}</div>
        </div>
      );
    }
    case "human_approval":
      return <p className="line-clamp-2 text-xs text-zinc-400">{node.approval_message || "A person approves before it continues."}</p>;
    case "join":
      return <p className="text-xs text-zinc-400">Waits for {node.join_policy?.mode === "any" ? "any branch" : node.join_policy?.mode === "count" ? `${node.join_policy.min_required ?? "N"} branches` : "every branch"}</p>;
    case "output":
      return (
        <div className="flex flex-wrap gap-1.5">
          <Chip>{node.output_config?.format === "text" ? "Plain text" : node.output_config?.format === "json" ? "JSON" : node.output_config?.format === "formatted" ? "Report" : "Auto"}</Chip>
          <Chip>Sources</Chip>
        </div>
      );
  }
}

function FlowNodeView({ data, selected }: NodeProps<FlowNodeType>) {
  const ctx = useContext(CanvasContext);
  const { node } = data;
  const look = LOOK[node.type];
  if (!ctx) return null;
  const hasProblems = data.problems.length > 0;
  return (
    <div
      className={cn(
        "w-[270px] overflow-hidden rounded-2xl border bg-[#141418] text-left shadow-xl shadow-black/40 transition-shadow",
        selected ? "border-indigo-400" : hasProblems ? "border-red-500/60" : "border-white/10",
        data.state && RING[data.state],
      )}
      title={hasProblems ? data.problems.map((p) => p.message).join("\n") : undefined}
    >
      {!NO_INPUT.includes(node.type) && <Handle type="target" position={Position.Left} className="!h-3 !w-3 !border-2 !border-[#141418] !bg-indigo-400" />}
      <div className={cn("flex items-center gap-2.5 bg-gradient-to-r px-3 py-2.5", look.head)}>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/15 text-white"><look.Icon className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-white">{look.label}</p>
          <p className="truncate text-[11px] text-white/80">{data.title !== look.label ? data.title : look.hint}</p>
        </div>
        {hasProblems && (
          <span className="flex items-center gap-0.5 rounded-full bg-black/30 px-1.5 py-0.5 text-[10px] font-semibold text-red-200">
            <AlertTriangle className="h-3 w-3" /> {data.problems.length}
          </span>
        )}
        <StateIcon state={data.state} />
      </div>
      <div className="px-3 py-2.5">
        <Body node={node} ctx={ctx} />
        {data.detail && <p className="mt-2 truncate rounded-md bg-sky-500/10 px-2 py-1 text-[10.5px] text-sky-300">{data.detail}</p>}
        {data.output && !data.detail && (
          <p className="mt-2 line-clamp-2 rounded-md bg-white/5 px-2 py-1 text-[10.5px] text-zinc-400" title={data.output}>{data.output}</p>
        )}
      </div>
      {node.type !== "output" && <Handle type="source" position={Position.Right} className="!h-3 !w-3 !border-2 !border-[#141418] !bg-indigo-400" />}
    </div>
  );
}

export const FlowNode = memo(FlowNodeView);
export const flowNodeTypes = { flow: FlowNode };
