"use client";

import { createContext, memo, useContext, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Handle, NodeToolbar, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle, Bot, CalendarClock, CheckCircle2, CircleDot, Clock, Code2, Copy, FileText, GitBranch, Hand, Loader2, LogIn, Merge,
  Pin, Play, PlayCircle, Plus, Send, Settings2, Trash2, Wrench, XCircle,
} from "lucide-react";

import { ConnectButton, useMissingServers } from "@/components/connections/connect-button";
import { ConnectorIcon } from "@/components/connections/connector-icon";
import { builderApi } from "@/lib/builder/api";
import { PALETTE, canAddAfter, isTrigger, serverIdOf, toolName } from "@/lib/builder/graph";
import { formatDuration, type StepState } from "@/lib/builder/run-state";
import { describeSchedule } from "@/lib/builder/schedule";
import type { Agent, NodeType, Problem, ToolNeed, WorkflowEdge, WorkflowNode } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** What the canvas shares with its nodes (so node bubbles stay clean and actions stay interactive). */
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
  /** The step's output from the last run on the canvas (or pinned mock output). */
  output?: string | null;
  /** Execution duration in milliseconds once the step finishes. */
  durationMs?: number | null;
  /** Epoch ms when an active running step started (ticks live). */
  runningSince?: number | null;
  /** True when the user pinned a sample/mock output to this step. */
  pinned?: boolean;
};
export type FlowNodeType = Node<FlowNodeData, "flow">;

type Look = {
  label: string;
  badge: string;
  hint: string;
  Icon: typeof Bot;
  head: string;
  ring: string;
  glow: string;
};

const LOOK: Record<NodeType, Look> = {
  input: {
    label: "Input",
    badge: "Trigger",
    hint: "Entry point for workflow run",
    Icon: LogIn,
    head: "from-sky-400 to-sky-600",
    ring: "border-sky-400/50",
    glow: "shadow-[0_0_24px_-4px_rgba(56,189,248,0.45)]",
  },
  manual_trigger: {
    label: "Manual Trigger",
    badge: "Trigger",
    hint: "Starts when Run is clicked",
    Icon: PlayCircle,
    head: "from-blue-500 to-indigo-600",
    ring: "border-blue-400/50",
    glow: "shadow-[0_0_24px_-4px_rgba(96,165,250,0.45)]",
  },
  schedule_trigger: {
    label: "Schedule Trigger",
    badge: "Schedule",
    hint: "Starts on a schedule",
    Icon: CalendarClock,
    head: "from-teal-400 to-teal-600",
    ring: "border-teal-400/50",
    glow: "shadow-[0_0_24px_-4px_rgba(45,212,191,0.45)]",
  },
  agent: {
    label: "Agent",
    badge: "Agent",
    hint: "AI agent performs processing",
    Icon: Bot,
    head: "from-violet-500 to-purple-600",
    ring: "border-violet-400/55",
    glow: "shadow-[0_0_26px_-4px_rgba(139,92,246,0.5)]",
  },
  tool: {
    label: "Tool Call",
    badge: "Tool",
    hint: "Calls one tool of a connector",
    Icon: Wrench,
    head: "from-orange-400 to-orange-600",
    ring: "border-orange-400/50",
    glow: "shadow-[0_0_24px_-4px_rgba(251,146,60,0.45)]",
  },
  condition: {
    label: "Condition",
    badge: "Router",
    hint: "Branches logic",
    Icon: GitBranch,
    head: "from-amber-400 to-amber-600",
    ring: "border-amber-400/50",
    glow: "shadow-[0_0_24px_-4px_rgba(251,191,36,0.45)]",
  },
  join: {
    label: "Join",
    badge: "Join",
    hint: "Waits for parallel branches",
    Icon: Merge,
    head: "from-slate-400 to-slate-600",
    ring: "border-slate-400/45",
    glow: "shadow-[0_0_20px_-4px_rgba(148,163,184,0.35)]",
  },
  human_approval: {
    label: "Human Approval",
    badge: "Approval",
    hint: "Pauses for a person to approve",
    Icon: Hand,
    head: "from-rose-500 to-red-600",
    ring: "border-rose-400/50",
    glow: "shadow-[0_0_24px_-4px_rgba(244,63,94,0.45)]",
  },
  output: {
    label: "Output",
    badge: "Output",
    hint: "Final answer",
    Icon: Send,
    head: "from-emerald-400 to-green-600",
    ring: "border-emerald-400/50",
    glow: "shadow-[0_0_24px_-4px_rgba(52,211,153,0.45)]",
  },
  code: {
    label: "Code",
    badge: "Code",
    hint: "Sorts and checks, without AI",
    Icon: Code2,
    head: "from-zinc-400 to-zinc-600",
    ring: "border-zinc-400/45",
    glow: "shadow-[0_0_20px_-4px_rgba(161,161,170,0.35)]",
  },
};
export const NODE_LOOK = LOOK;

const STATE_RING: Record<StepState, string> = {
  running: "ring-4 ring-sky-400/50 border-sky-400 shadow-[0_0_32px_rgba(56,189,248,0.65)]",
  succeeded: "ring-2 ring-emerald-400/80 border-emerald-400 shadow-[0_0_24px_-4px_rgba(52,211,153,0.5)]",
  failed: "ring-2 ring-red-500/80 border-red-500 shadow-[0_0_24px_-4px_rgba(239,68,68,0.5)]",
  waiting: "ring-4 ring-amber-400/50 border-amber-400 animate-pulse shadow-[0_0_28px_rgba(245,158,11,0.5)]",
  skipped: "opacity-45",
};
const NO_INPUT: NodeType[] = ["input", "manual_trigger", "schedule_trigger"];

function StateBadge({ state }: { state?: StepState }) {
  if (!state || state === "skipped") return null;
  if (state === "running") {
    return (
      <span className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full border border-sky-400/50 bg-zinc-950 shadow-md" aria-label="Running">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-400" />
      </span>
    );
  }
  if (state === "succeeded") {
    return (
      <span className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full border border-emerald-400/50 bg-zinc-950 shadow-md" aria-label="Done">
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full border border-red-500/50 bg-zinc-950 shadow-md" aria-label="Failed">
        <XCircle className="h-3.5 w-3.5 text-red-400" />
      </span>
    );
  }
  return (
    <span className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full border border-amber-400/50 bg-zinc-950 shadow-md" aria-label="Waiting for you">
      <CircleDot className="h-3.5 w-3.5 text-amber-400" />
    </span>
  );
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
        "nodrag flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-zinc-300 transition-colors cursor-pointer [&_svg]:h-3.5 [&_svg]:w-3.5",
        danger ? "hover:bg-red-500/15 hover:text-red-300" : "hover:bg-white/10 hover:text-white",
      )}
    >
      {children}
    </button>
  );
}

/** Quick floating toolbar shown above the bubble on hover or when selected. */
function StepToolbar({
  node,
  ctx,
  hasResult,
  visible,
  onEnter,
  onLeave,
}: {
  node: WorkflowNode;
  ctx: CanvasCtx;
  hasResult: boolean;
  visible: boolean;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const [nextOpen, setNextOpen] = useState(false);
  const trigger = isTrigger(node.type);

  useEffect(() => {
    if (!visible) setNextOpen(false);
  }, [visible]);

  return (
    <NodeToolbar isVisible={visible} position={Position.Top} offset={10} className="relative">
      <div
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
        className="animate-scale-in flex items-center gap-0.5 rounded-xl border border-white/15 bg-[#18181d]/95 p-1 shadow-2xl shadow-black/60 backdrop-blur-md"
      >
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
        <div
          onMouseEnter={onEnter}
          onMouseLeave={onLeave}
          className="animate-scale-in absolute left-0 top-full z-20 mt-1.5 w-52 rounded-xl border border-white/15 bg-[#18181d]/95 p-1.5 shadow-2xl shadow-black/70 backdrop-blur-md"
        >
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
                className="nodrag flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-zinc-200 transition-colors hover:bg-white/10 cursor-pointer"
              >
                <span className={cn("flex h-5 w-5 items-center justify-center rounded-md bg-gradient-to-br text-white", look.head)}><look.Icon className="h-3 w-3" /></span>
                <span>{look.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </NodeToolbar>
  );
}

/** Compact 1-line subtitle + optional Connect action under the circular bubble. */
function BubbleMeta({ node, ctx }: { node: WorkflowNode; ctx: CanvasCtx }) {
  const serverId = node.type === "tool" ? serverIdOf(node.tool_id) : null;
  const server = useQuery({
    queryKey: ["builder-server-tools", serverId],
    queryFn: () => builderApi.serverTools(ctx.token, serverId!),
    enabled: !!ctx.token && !!serverId,
    staleTime: 60_000,
  });

  const agent = node.type === "agent" ? (node.draft_agent ?? (node.agent_id ? ctx.agents[node.agent_id] : undefined)) : undefined;
  const own = node.config_overrides ?? {};
  const agentToolIds = agent ? ((own.tool_ids as string[] | undefined) ?? agent.config?.tool_ids ?? []) : [];
  const missing = useMissingServers(ctx.token, agentToolIds);
  const connectable = missing.filter((m) => !m.removed);
  const agentNeeds = agent ? ((own.tool_needs as ToolNeed[] | undefined) ?? agent.config?.tool_needs ?? []) : [];

  let sub = LOOK[node.type].badge;
  if (node.type === "input") {
    sub = ctx.inputText.trim() ? `"${ctx.inputText.trim()}"` : "Click to set prompt";
  } else if (node.type === "manual_trigger") {
    sub = "Press Run to start";
  } else if (node.type === "schedule_trigger") {
    sub = describeSchedule(node.schedule);
  } else if (node.type === "tool") {
    if (!node.tool_id) sub = node.need || "Pick a tool";
    else sub = server.data?.server_name ? `${server.data.server_name} · ${toolName(node.tool_id)}` : toolName(node.tool_id);
  } else if (node.type === "agent") {
    if (!agent) sub = "Set up agent";
    else if (agentToolIds.length) sub = `${agentToolIds.length} tool${agentToolIds.length === 1 ? "" : "s"}`;
    else sub = (own.llm_model as string | undefined) || agent.llm_model || "AI Agent";
  } else if (node.type === "condition") {
    const outs = ctx.edges.filter((e) => e.source === node.id).map((e) => e.condition).filter(Boolean);
    sub = outs.length ? outs.join(" / ") : (node.condition_config?.mode === "rule" ? "Rule branch" : "AI branch");
  } else if (node.type === "human_approval") {
    sub = "Waits for approval";
  } else if (node.type === "join") {
    sub = node.join_policy?.mode === "any" ? "Any branch" : "All branches";
  } else if (node.type === "output") {
    const fmt = node.output_config?.format;
    sub = fmt === "text" ? "Plain text" : fmt === "json" ? "JSON" : fmt === "formatted" ? "Report" : "Final answer";
  }

  const disconnectedTool = node.type === "tool" && serverId && server.data && !server.data.connected;

  return (
    <>
      <p className="mt-0.5 max-w-[168px] truncate text-[11px] text-zinc-400" title={sub}>
        {sub}
      </p>
      {disconnectedTool && (
        <div className="nodrag mt-1.5 flex justify-center" onClick={(e) => e.stopPropagation()}>
          <ConnectButton serverId={serverId!} serverName={server.data!.server_name} token={ctx.token} className="rounded-full px-2.5 py-0.5 text-[11px]" />
        </div>
      )}
      {connectable.length > 0 && (
        <div className="nodrag mt-1.5 flex flex-wrap justify-center gap-1" onClick={(e) => e.stopPropagation()}>
          {connectable.slice(0, 2).map((m) => (
            <ConnectButton key={m.serverId} serverId={m.serverId} serverName={m.name} token={ctx.token} className="rounded-full px-2 py-0.5 text-[11px]" />
          ))}
        </div>
      )}
      {node.type === "agent" && agentNeeds.length > 0 && connectable.length === 0 && (
        <span className="mt-1 inline-block rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
          Needs {agentNeeds.length} app{agentNeeds.length === 1 ? "" : "s"}
        </span>
      )}
    </>
  );
}

/** Real ConnectorIcon inside the circular bubble for tool steps when available. */
function BubbleIcon({ node, ctx }: { node: WorkflowNode; ctx: CanvasCtx }) {
  const look = LOOK[node.type];
  const serverId = node.type === "tool" ? serverIdOf(node.tool_id) : null;
  const server = useQuery({
    queryKey: ["builder-server-tools", serverId],
    queryFn: () => builderApi.serverTools(ctx.token, serverId!),
    enabled: !!ctx.token && !!serverId,
    staleTime: 60_000,
  });

  if (node.type === "tool" && server.data?.server_name) {
    return (
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/95 p-2 shadow-inner ring-1 ring-white/20">
        <ConnectorIcon name={server.data.server_name} size="md" className="h-7 w-7 bg-transparent p-0" />
      </div>
    );
  }

  return (
    <span className={cn("flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-br text-white shadow-inner ring-1 ring-white/20", look.head)}>
      <look.Icon className="h-5 w-5" />
    </span>
  );
}

function LiveTimer({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [since]);
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-sky-400/35 bg-sky-500/15 px-2 py-0.5 text-[10px] font-medium tabular-nums text-sky-300">
      <Clock className="h-2.5 w-2.5 animate-pulse" />
      {formatDuration(Math.max(0, now - since))}
    </span>
  );
}

function FlowNodeView({ data, selected }: NodeProps<FlowNodeType>) {
  const ctx = useContext(CanvasContext);
  const [hovered, setHovered] = useState(false);
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  if (!ctx) return null;
  const { node } = data;
  const look = LOOK[node.type];
  const hasProblems = data.problems.length > 0;
  const isRunning = data.state === "running" || data.state === "waiting";
  const displayTitle = data.title !== look.label ? data.title : look.label;

  const enter = () => {
    if (leaveTimer.current) {
      clearTimeout(leaveTimer.current);
      leaveTimer.current = null;
    }
    setHovered(true);
  };
  const leave = () => {
    if (leaveTimer.current) clearTimeout(leaveTimer.current);
    leaveTimer.current = setTimeout(() => setHovered(false), 160);
  };

  return (
    <div
      onMouseEnter={enter}
      onMouseLeave={leave}
      className="animate-scale-in group relative flex w-44 flex-col items-center text-center select-none"
      title={hasProblems ? data.problems.map((p) => p.message).join("\n") : undefined}
    >
      <StepToolbar
        node={node}
        ctx={ctx}
        hasResult={!!data.output}
        visible={!!selected || hovered}
        onEnter={enter}
        onLeave={leave}
      />

      {/* Circular Make.com-style orb with left/right ports anchored to the circle perimeter */}
      <div className="relative flex items-center justify-center">
        {/* Glowing animated halo when running/waiting */}
        {isRunning && (
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute -inset-1.5 rounded-full opacity-55 blur-md animate-pulse bg-gradient-to-tr",
              look.head,
            )}
          />
        )}

        {!NO_INPUT.includes(node.type) && (
          <Handle
            type="target"
            position={Position.Left}
            className="!-left-1.5 !h-3 !w-3 !border-2 !border-[var(--surface)] !bg-indigo-400 transition-transform hover:scale-125"
          />
        )}

        <div
          className={cn(
            "relative flex h-20 w-20 items-center justify-center rounded-full border-2 bg-[var(--surface-raised)] transition-all duration-200 group-hover:scale-105",
            hasProblems ? "border-red-500/80 shadow-[0_0_20px_-4px_rgba(239,68,68,0.45)]" : cn(look.ring, look.glow),
            selected && "ring-4 ring-[var(--accent-hover)]/45 border-[var(--accent-hover)] scale-105",
            data.state && STATE_RING[data.state],
          )}
        >
          {/* Subtle inner gradient sheen */}
          <span aria-hidden className={cn("pointer-events-none absolute inset-1 rounded-full bg-gradient-to-b opacity-15", look.head)} />
          <BubbleIcon node={node} ctx={ctx} />

          <StateBadge state={data.state} />

          {hasProblems && (
            <span className="absolute -left-1 -top-1 flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-full border border-red-500/50 bg-zinc-950 px-1 text-[11px] font-bold text-red-400 shadow-md">
              <AlertTriangle className="h-3 w-3" />
              {data.problems.length > 1 && data.problems.length}
            </span>
          )}
        </div>

        {node.type !== "output" && (
          <Handle
            type="source"
            position={Position.Right}
            className="!-right-1.5 !h-3 !w-3 !border-2 !border-[var(--surface)] !bg-indigo-400 transition-transform hover:scale-125"
          />
        )}
      </div>

      {/* Clean label & 1-line subtitle underneath the circle */}
      <div className="mt-2 flex w-full flex-col items-center px-1">
        <p className="max-w-[168px] truncate text-xs font-semibold text-zinc-100 group-hover:text-white transition-colors">
          {displayTitle}
        </p>
        <BubbleMeta node={node} ctx={ctx} />

        {data.detail && (
          <span className="mt-1.5 inline-flex max-w-[168px] items-center gap-1 truncate rounded-full border border-sky-400/30 bg-sky-500/15 px-2 py-0.5 text-[10px] font-medium text-sky-300">
            {data.state === "running" && <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-sky-400" />}
            <span className="truncate">{data.detail}</span>
          </span>
        )}

        {!data.detail && (data.pinned || data.runningSince || data.durationMs != null || data.output) && (
          <div className="mt-1.5 flex flex-wrap items-center justify-center gap-1">
            {data.runningSince && data.state === "running" ? (
              <LiveTimer since={data.runningSince} />
            ) : data.durationMs != null ? (
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium tabular-nums",
                  data.state === "failed"
                    ? "border-red-400/30 bg-red-500/15 text-red-300"
                    : "border-emerald-400/30 bg-emerald-500/12 text-emerald-300",
                )}
              >
                <Clock className="h-2.5 w-2.5" />
                {formatDuration(data.durationMs)}
              </span>
            ) : null}

            {data.pinned && (
              <span
                className="inline-flex items-center gap-0.5 rounded-full border border-amber-400/35 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-300"
                title="Pinned sample output active for downstream step tests"
              >
                <Pin className="h-2.5 w-2.5" />
                Pinned
              </span>
            )}

            {data.output && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  ctx.showResult(node.id);
                }}
                className="nodrag inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.05] px-2 py-0.5 text-[10px] font-medium text-zinc-300 transition-colors hover:border-indigo-400/40 hover:bg-indigo-500/15 hover:text-white cursor-pointer"
                title={data.output}
              >
                <FileText className="h-2.5 w-2.5 text-indigo-400" /> Data
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export const FlowNode = memo(FlowNodeView);
export const flowNodeTypes = { flow: FlowNode };
