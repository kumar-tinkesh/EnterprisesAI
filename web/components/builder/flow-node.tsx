"use client";

import { createContext, memo, useContext, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Handle, NodeToolbar, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle, BookOpen, Bot, CalendarClock, CheckCircle2, CircleDot, Copy, FileText, GitBranch, Hand, Loader2, LogIn, Merge,
  Play, PlayCircle, Plus, RotateCcw, Send, Settings2, Trash2, Unplug, Wrench, XCircle,
} from "lucide-react";

import { ConnectButton, useMissingServers } from "@/components/connections/connect-button";
import { SystemsChip } from "@/components/builder/tool-needs";
import { builderApi } from "@/lib/builder/api";
import { PALETTE, canAddAfter, isTrigger, overriddenParams, serverIdOf, toolName } from "@/lib/builder/graph";
import type { StepState } from "@/lib/builder/run-state";
import { describeSchedule } from "@/lib/builder/schedule";
import type { Agent, NodeType, Problem, ToolNeed, WorkflowEdge, WorkflowNode } from "@/lib/builder/types";
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
  /** Show the step's settings. */
  open: (nodeId: string) => void;
  duplicate: (nodeId: string) => void;
  remove: (nodeId: string) => void;
  /** A new step of ``type`` right after this one. */
  addAfter: (nodeId: string, type: NodeType) => void;
  /** Run this step by itself (agent and tool steps that are set up). */
  test: (nodeId: string) => void;
  canTest: (node: WorkflowNode) => boolean;
  /** Show the step's whole answer from the last run. */
  showResult: (nodeId: string) => void;
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

/** Each kind of step has its own colour on the canvas — the card's tint, border, header and badge —
 *  so an agent, a tool call or an approval can be told apart at a glance. */
type Look = { label: string; badge: string; hint: string; Icon: typeof Bot; head: string; card: string; tag: string };
// One hue per kind, far enough apart to tell at a glance: triggers in blues/teal, agent violet,
// tool orange, condition yellow, join neutral slate, approval rose, output green.
const LOOK: Record<NodeType, Look> = {
  input: {
    label: "Input", badge: "Trigger", hint: "Entry point for workflow run", Icon: LogIn, head: "from-sky-400 to-sky-600",
    card: "border-sky-500/45 bg-gradient-to-b from-sky-500/[0.14] to-[#141418]", tag: "bg-sky-500/15 text-sky-200 ring-sky-400/30",
  },
  manual_trigger: {
    label: "Manual Trigger", badge: "Trigger", hint: "Starts when Run is clicked", Icon: PlayCircle, head: "from-blue-500 to-indigo-600",
    card: "border-blue-500/45 bg-gradient-to-b from-blue-500/[0.14] to-[#141418]", tag: "bg-blue-500/15 text-blue-200 ring-blue-400/30",
  },
  schedule_trigger: {
    label: "Schedule Trigger", badge: "Trigger", hint: "Starts on a schedule", Icon: CalendarClock, head: "from-teal-400 to-teal-600",
    card: "border-teal-500/45 bg-gradient-to-b from-teal-500/[0.14] to-[#141418]", tag: "bg-teal-500/15 text-teal-200 ring-teal-400/30",
  },
  agent: {
    label: "Agent", badge: "Agent", hint: "AI agent performs processing", Icon: Bot, head: "from-violet-500 to-purple-600",
    card: "border-violet-500/45 bg-gradient-to-b from-violet-500/[0.14] to-[#141418]", tag: "bg-violet-500/15 text-violet-200 ring-violet-400/30",
  },
  tool: {
    label: "Tool Call", badge: "Tool", hint: "Calls one tool of a connector", Icon: Wrench, head: "from-orange-400 to-orange-600",
    card: "border-orange-500/45 bg-gradient-to-b from-orange-500/[0.14] to-[#141418]", tag: "bg-orange-500/15 text-orange-200 ring-orange-400/30",
  },
  condition: {
    label: "Condition", badge: "Condition", hint: "Branches logic", Icon: GitBranch, head: "from-yellow-400 to-amber-500",
    card: "border-yellow-500/45 bg-gradient-to-b from-yellow-500/[0.14] to-[#141418]", tag: "bg-yellow-500/15 text-yellow-200 ring-yellow-400/30",
  },
  join: {
    label: "Join", badge: "Join", hint: "Waits for parallel branches", Icon: Merge, head: "from-slate-400 to-slate-600",
    card: "border-slate-500/45 bg-gradient-to-b from-slate-500/[0.14] to-[#141418]", tag: "bg-slate-500/15 text-slate-200 ring-slate-400/30",
  },
  human_approval: {
    label: "Human Approval", badge: "Approval", hint: "Pauses for a person to approve", Icon: Hand, head: "from-rose-500 to-red-600",
    card: "border-rose-500/45 bg-gradient-to-b from-rose-500/[0.14] to-[#141418]", tag: "bg-rose-500/15 text-rose-200 ring-rose-400/30",
  },
  output: {
    label: "Output", badge: "Output", hint: "Final answer", Icon: Send, head: "from-emerald-400 to-green-600",
    card: "border-emerald-500/45 bg-gradient-to-b from-emerald-500/[0.14] to-[#141418]", tag: "bg-emerald-500/15 text-emerald-200 ring-emerald-400/30",
  },
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
  if (state === "running") return <Loader2 className="h-4 w-4 animate-spin text-sky-400" aria-label="Running" />;
  if (state === "succeeded") return <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-label="Done" />;
  if (state === "failed") return <XCircle className="h-4 w-4 text-red-400" aria-label="Failed" />;
  if (state === "waiting") return <CircleDot className="h-4 w-4 text-amber-400" aria-label="Waiting for you" />;
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
  return <span title={title} className={cn("inline-flex max-w-full items-center gap-1 truncate rounded-md border px-1.5 py-0.5 text-xs", tones[tone])}>{children}</span>;
}

/** "N tools" on an agent step; click it for the list (in a layer of its own,
 *  so the node card doesn't clip it). Amber when the step changed them; red, with a Connect
 *  per system, when some belong to a system this user hasn't connected. */
function ToolsChip({ toolIds, changed, token }: { toolIds: string[]; changed: boolean; token: string }) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLButtonElement>(null);
  const missing = useMissingServers(token, toolIds);
  const offline = new Set(missing.flatMap((m) => m.tools));
  const removed = new Set(missing.filter((m) => m.removed).flatMap((m) => m.tools));
  const connectable = missing.filter((m) => !m.removed);
  if (toolIds.length === 0) return null;
  return (
    <>
      <button
        ref={ref}
        type="button"
        title={
          removed.size ? `${removed.size} of these tools belong to a removed system — open the step and pick its tools again`
            : offline.size ? `${offline.size} of these tools won't run until you connect ${connectable.map((m) => m.name).join(", ")}` : "Tools this step can call"
        }
        aria-expanded={!!at}
        onClick={(e) => {
          e.stopPropagation();
          const r = ref.current?.getBoundingClientRect();
          setAt(at || !r ? null : { top: r.bottom + 4, left: r.left });
        }}
        className={cn(
          "nodrag inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs cursor-pointer",
          offline.size
            ? "border-red-400/40 bg-red-500/10 text-red-300 hover:bg-red-500/20"
            : changed ? "border-amber-400/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20" : "border-violet-400/30 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20",
        )}
      >
        <Wrench className="h-3 w-3" /> {toolIds.length} tool{toolIds.length === 1 ? "" : "s"}
        {removed.size > 0 && <span className="inline-flex items-center gap-0.5"><XCircle className="h-3 w-3" /> {removed.size} removed</span>}
        {offline.size - removed.size > 0 && <span className="inline-flex items-center gap-0.5"><Unplug className="h-3 w-3" /> {offline.size - removed.size} not connected</span>}
      </button>
      {at &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[999]" onClick={() => setAt(null)} />
            <div style={at} className="fixed z-[1000] max-h-72 w-64 overflow-y-auto rounded-lg border border-white/10 bg-zinc-900 p-1.5 shadow-2xl">
              <p className="px-1.5 pb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">Tools this step can call</p>
              {toolIds.map((id) => (
                <p key={id} title={id} className="flex items-center gap-1.5 truncate rounded px-1.5 py-1 text-xs text-zinc-200 hover:bg-white/5">
                  {offline.has(id) ? <Unplug className="h-3 w-3 shrink-0 text-red-400" /> : <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />}
                  <span className="truncate">{toolName(id)}</span>
                  {offline.has(id) && <span className="ml-auto shrink-0 text-xs text-red-300">{removed.has(id) ? "system removed" : "not connected"}</span>}
                </p>
              ))}
              {connectable.length > 0 && (
                <div className="mt-1 space-y-1 border-t border-white/10 px-1.5 pt-1.5">
                  {connectable.map((m) => (
                    <ConnectButton key={m.serverId} serverId={m.serverId} serverName={m.name} token={token} className="w-full justify-center px-2 py-1 text-xs" />
                  ))}
                </div>
              )}
            </div>
          </>,
          document.body,
        )}
      {/* Right on the card too, so it's clear before pressing Run. */}
      {connectable.map((m) => (
        <ConnectButton key={m.serverId} serverId={m.serverId} serverName={m.name} token={token} className="rounded-md px-1.5 py-0.5 text-xs" />
      ))}
    </>
  );
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
            <ConnectButton serverId={serverId!} serverName={server.data.server_name} token={ctx.token} className="rounded-full px-2 py-0.5 text-xs" />
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
      <div className="flex flex-wrap gap-x-3 text-xs">
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
          <p className="mb-1.5 text-center text-xs font-semibold uppercase tracking-wider text-zinc-500">Start trigger query</p>
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
      // What the step really runs with: its own overrides over the agent's.
      const own = node.config_overrides ?? {};
      const toolIds = (own.tool_ids as string[] | undefined) ?? a.config?.tool_ids ?? [];
      const needs = (own.tool_needs as ToolNeed[] | undefined) ?? a.config?.tool_needs ?? [];
      const kbs = ((own.knowledge_base_ids as string[] | undefined) ?? a.config?.knowledge_base_ids ?? []).length;
      const attempts = node.retry?.max_attempts ?? 1;
      const overrides = overriddenParams(node.config_overrides).length;
      const model = (node.config_overrides?.llm_model as string | undefined) || a.llm_model;
      return (
        <div className="flex flex-wrap gap-1.5">
          <Chip tone={model !== a.llm_model ? "amber" : "zinc"}><span className="font-mono">{model || "default model"}</span></Chip>
          <ToolsChip toolIds={toolIds} changed={"tool_ids" in own} token={ctx.token} />
          <SystemsChip token={ctx.token} needs={needs} />
          {kbs > 0 && <Chip tone={"knowledge_base_ids" in own ? "amber" : "sky"}><BookOpen className="h-3 w-3" /> {kbs}</Chip>}
          {attempts > 1 && <Chip title={`Tried up to ${attempts} times if it fails`}><RotateCcw className="h-3 w-3" /> {attempts}</Chip>}
          {node.draft_agent && <Chip tone="amber">{node.agent_id ? "customized" : "new — saved with the workflow"}</Chip>}
          {overrides > 0 && <Chip tone="amber">{overrides} setting{overrides === 1 ? "" : "s"} changed</Chip>}
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

function ToolButton({ label, danger, onClick, children }: { label: string; danger?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={cn(
        "nodrag flex h-7 items-center gap-1 rounded-md px-1.5 text-xs font-medium text-zinc-300 transition-colors cursor-pointer [&_svg]:h-3.5 [&_svg]:w-3.5",
        danger ? "hover:bg-red-500/15 hover:text-red-300" : "hover:bg-white/10 hover:text-white",
      )}
    >
      {children}
    </button>
  );
}

/** Above the selected step: what you can do with it. */
function StepToolbar({ node, ctx, hasResult }: { node: WorkflowNode; ctx: CanvasCtx; hasResult: boolean }) {
  const [nextOpen, setNextOpen] = useState(false);
  const trigger = isTrigger(node.type);
  return (
    <NodeToolbar position={Position.Top} offset={8} className="relative">
      <div className="flex items-center gap-0.5 rounded-lg border border-white/10 bg-[#1c1c21] p-0.5 shadow-lg shadow-black/40">
        {ctx.canTest(node) && (
          <ToolButton label="Test this step by itself" onClick={() => ctx.test(node.id)}>
            <Play /> Test
          </ToolButton>
        )}
        {hasResult && (
          <ToolButton label="This step's answer from the last run" onClick={() => ctx.showResult(node.id)}>
            <FileText /> Result
          </ToolButton>
        )}
        <ToolButton label="Configure this step" onClick={() => ctx.open(node.id)}>
          <Settings2 /> Configure
        </ToolButton>
        {!ctx.readOnly && (
          <>
            {canAddAfter(node.type) && (
              <ToolButton label="Add a step after this one" onClick={() => setNextOpen((o) => !o)}>
                <Plus /> Next
              </ToolButton>
            )}
            {!trigger && (
              <>
                <span className="mx-0.5 h-4 w-px bg-white/10" />
                <ToolButton label="Copy this step" onClick={() => ctx.duplicate(node.id)}><Copy /></ToolButton>
                <ToolButton label="Delete this step" danger onClick={() => ctx.remove(node.id)}><Trash2 /></ToolButton>
              </>
            )}
          </>
        )}
      </div>
      {nextOpen && (
        <div className="absolute left-0 top-full z-10 mt-1 w-52 rounded-lg border border-white/10 bg-[#1c1c21] p-1 shadow-xl shadow-black/50">
          {PALETTE.map((type) => {
            const look = LOOK[type];
            return (
              <button
                key={type}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setNextOpen(false);
                  ctx.addAfter(node.id, type);
                }}
                className="nodrag flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-zinc-200 hover:bg-white/10 cursor-pointer"
              >
                <span className={cn("flex h-5 w-5 items-center justify-center rounded bg-gradient-to-br text-white", look.head)}><look.Icon className="h-3 w-3" /></span> {look.label}
              </button>
            );
          })}
        </div>
      )}
    </NodeToolbar>
  );
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
        "w-[270px] overflow-hidden rounded-xl border text-left shadow-lg shadow-black/30 transition-shadow",
        // The kind's own border stays; a problem turns it red, selection adds an outline around it.
        hasProblems ? "border-red-500/70 bg-[#141418]" : look.card,
        selected && "outline outline-2 outline-offset-2 outline-indigo-400",
        data.state && RING[data.state],
      )}
      title={hasProblems ? data.problems.map((p) => p.message).join("\n") : undefined}
    >
      <StepToolbar node={node} ctx={ctx} hasResult={!!data.output} />
      {!NO_INPUT.includes(node.type) && <Handle type="target" position={Position.Left} className="!h-3 !w-3 !border-2 !border-[#141418] !bg-indigo-400" />}
      {/* The step's colour: a bar on top, its icon and its kind's badge. */}
      <div className={cn("h-1 bg-gradient-to-r", look.head)} />
      <div className="flex items-center gap-2.5 px-3 pt-2.5">
        <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br text-white shadow-md shadow-black/30", look.head)}><look.Icon className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold text-zinc-100">{data.title !== look.label ? data.title : look.label}</p>
          <p className="truncate text-[10.5px] text-zinc-400">{data.title !== look.label ? look.label : look.hint}</p>
        </div>
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider ring-1", look.tag)}>{look.badge}</span>
        {hasProblems && (
          <span className="flex items-center gap-0.5 rounded-full bg-red-500/15 px-1.5 py-0.5 text-xs font-semibold text-red-300">
            <AlertTriangle className="h-3 w-3" /> {data.problems.length}
          </span>
        )}
        <StateIcon state={data.state} />
      </div>
      <div className="px-3 py-2.5">
        <Body node={node} ctx={ctx} />
        {data.detail && <p className="mt-2 truncate rounded-md bg-sky-500/10 px-2 py-1 text-[10.5px] text-sky-300">{data.detail}</p>}
        {data.output && !data.detail && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              ctx.showResult(node.id);
            }}
            className="nodrag mt-2 line-clamp-2 w-full rounded-md bg-white/5 px-2 py-1 text-left text-[10.5px] text-zinc-400 hover:bg-white/10 hover:text-zinc-200 cursor-pointer"
            title="See the whole answer"
          >
            {data.output}
          </button>
        )}
      </div>
      {node.type !== "output" && <Handle type="source" position={Position.Right} className="!h-3 !w-3 !border-2 !border-[#141418] !bg-indigo-400" />}
    </div>
  );
}

export const FlowNode = memo(FlowNodeView);
export const flowNodeTypes = { flow: FlowNode };
