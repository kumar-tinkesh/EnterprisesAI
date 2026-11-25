"use client";

import { memo, useCallback, useState } from "react";
import { Handle, Position, type Node, type NodeChange, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle,
  BookOpen,
  Bot,
  CalendarClock,
  CheckCircle2,
  CircleDot,
  Code2,
  GitBranch,
  Hand,
  Loader2,
  LogIn,
  Merge,
  PlayCircle,
  Plug,
  Send,
  Users,
  Wrench,
  XCircle,
} from "lucide-react";

import { ConnectButton } from "@/components/connections/connect-button";
import { ConnectorIcon } from "@/components/connections/connector-icon";
import { cn } from "@/lib/utils";
import type { StepState } from "@/lib/builder/run-state";
import type { NodeType, Problem } from "@/lib/builder/types";

/** "knowledge", "server" and "team" only appear on the agent-mode canvas (a knowledge base feeding the agent; the connector its tools come from; an agent it hands work to). */
export type StepKind = NodeType | "knowledge" | "server" | "team";

export type StepData = {
  type: StepKind;
  title: string;
  subtitle: string;
  problems: Problem[];
  state?: StepState;
  detail?: string | null;
  /** Optional connector name (e.g. "Slack", "Gmail") to show its brand logo on server/tool bubbles. */
  serverName?: string;
  /** Lines come in at the top and leave at the bottom (narrow, top-to-bottom layouts). */
  vertical?: boolean;
  /** A connector that isn't connected yet: connect it right on the node. */
  connect?: { serverId: string; serverName: string; token: string };
};

export type StepNodeType = Node<StepData, "step">;

const ICONS: Record<StepKind, typeof Bot> = {
  knowledge: BookOpen,
  server: Plug,
  team: Users,
  input: LogIn,
  manual_trigger: PlayCircle,
  schedule_trigger: CalendarClock,
  agent: Bot,
  tool: Wrench,
  condition: GitBranch,
  join: Merge,
  human_approval: Hand,
  output: Send,
  code: Code2,
};

type StepLook = {
  badge: string;
  bar: string;
  ring: string;
  glow: string;
  iconBg: string;
  pill: string;
  handle: string;
};

const LOOKS: Record<StepKind, StepLook> = {
  agent: {
    badge: "AI Agent",
    bar: "from-indigo-500 via-violet-500 to-purple-500",
    ring: "border-indigo-400/55",
    glow: "shadow-[0_0_28px_-4px_rgba(99,102,241,0.5)]",
    iconBg: "from-indigo-500 to-violet-600 text-white",
    pill: "border-indigo-400/30 bg-indigo-500/15 text-indigo-300",
    handle: "!bg-indigo-400",
  },
  knowledge: {
    badge: "Knowledge",
    bar: "from-violet-500 to-purple-500",
    ring: "border-violet-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(139,92,246,0.45)]",
    iconBg: "from-violet-500 to-purple-600 text-white",
    pill: "border-violet-400/30 bg-violet-500/15 text-violet-300",
    handle: "!bg-violet-400",
  },
  server: {
    badge: "Connector",
    bar: "from-sky-400 to-cyan-500",
    ring: "border-sky-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(56,189,248,0.45)]",
    iconBg: "from-sky-500 to-cyan-600 text-white",
    pill: "border-sky-400/30 bg-sky-500/15 text-sky-300",
    handle: "!bg-sky-400",
  },
  tool: {
    badge: "Tool",
    bar: "from-emerald-400 to-teal-500",
    ring: "border-emerald-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(52,211,153,0.45)]",
    iconBg: "from-emerald-500 to-teal-600 text-white",
    pill: "border-emerald-400/30 bg-emerald-500/15 text-emerald-300",
    handle: "!bg-emerald-400",
  },
  team: {
    badge: "Sub-agent",
    bar: "from-fuchsia-500 to-pink-500",
    ring: "border-fuchsia-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(217,70,239,0.45)]",
    iconBg: "from-fuchsia-500 to-pink-600 text-white",
    pill: "border-fuchsia-400/30 bg-fuchsia-500/15 text-fuchsia-300",
    handle: "!bg-fuchsia-400",
  },
  input: {
    badge: "Trigger",
    bar: "from-sky-400 to-blue-500",
    ring: "border-sky-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(56,189,248,0.45)]",
    iconBg: "from-sky-400 to-blue-600 text-white",
    pill: "border-sky-400/30 bg-sky-500/15 text-sky-300",
    handle: "!bg-sky-400",
  },
  manual_trigger: {
    badge: "Trigger",
    bar: "from-blue-400 to-indigo-500",
    ring: "border-blue-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(96,165,250,0.45)]",
    iconBg: "from-blue-500 to-indigo-600 text-white",
    pill: "border-blue-400/30 bg-blue-500/15 text-blue-300",
    handle: "!bg-blue-400",
  },
  schedule_trigger: {
    badge: "Schedule",
    bar: "from-teal-400 to-emerald-500",
    ring: "border-teal-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(45,212,191,0.45)]",
    iconBg: "from-teal-400 to-emerald-600 text-white",
    pill: "border-teal-400/30 bg-teal-500/15 text-teal-300",
    handle: "!bg-teal-400",
  },
  condition: {
    badge: "Condition",
    bar: "from-amber-400 to-orange-500",
    ring: "border-amber-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(251,191,36,0.45)]",
    iconBg: "from-amber-400 to-orange-500 text-white",
    pill: "border-amber-400/30 bg-amber-500/15 text-amber-300",
    handle: "!bg-amber-400",
  },
  join: {
    badge: "Join",
    bar: "from-slate-400 to-zinc-500",
    ring: "border-slate-400/45",
    glow: "shadow-[0_0_18px_-4px_rgba(148,163,184,0.35)]",
    iconBg: "from-slate-500 to-zinc-600 text-white",
    pill: "border-white/15 bg-white/10 text-zinc-300",
    handle: "!bg-slate-400",
  },
  human_approval: {
    badge: "Approval",
    bar: "from-rose-500 to-red-500",
    ring: "border-rose-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(244,63,94,0.45)]",
    iconBg: "from-rose-500 to-red-600 text-white",
    pill: "border-rose-400/30 bg-rose-500/15 text-rose-300",
    handle: "!bg-rose-400",
  },
  output: {
    badge: "Output",
    bar: "from-emerald-400 to-green-500",
    ring: "border-emerald-400/50",
    glow: "shadow-[0_0_22px_-4px_rgba(52,211,153,0.45)]",
    iconBg: "from-emerald-400 to-green-600 text-white",
    pill: "border-emerald-400/30 bg-emerald-500/15 text-emerald-300",
    handle: "!bg-emerald-400",
  },
  code: {
    badge: "Code",
    bar: "from-zinc-400 to-zinc-500",
    ring: "border-zinc-400/45",
    glow: "shadow-[0_0_18px_-4px_rgba(161,161,170,0.35)]",
    iconBg: "from-zinc-500 to-zinc-700 text-white",
    pill: "border-white/15 bg-white/10 text-zinc-300",
    handle: "!bg-zinc-400",
  },
};

const STATE_RING: Record<StepState, string> = {
  running: "ring-4 ring-sky-400/50 border-sky-400 shadow-[0_0_30px_rgba(56,189,248,0.6)]",
  succeeded: "ring-2 ring-emerald-400/85 border-emerald-400 shadow-[0_0_22px_-4px_rgba(52,211,153,0.45)]",
  failed: "ring-2 ring-red-500/85 border-red-500 shadow-[0_0_22px_-4px_rgba(239,68,68,0.45)]",
  waiting: "ring-4 ring-amber-400/50 border-amber-400 animate-pulse",
  skipped: "opacity-45",
};

const NO_INPUT: StepKind[] = ["input", "manual_trigger", "schedule_trigger", "knowledge"];

function StateBadge({ state }: { state?: StepState }) {
  if (!state || state === "skipped") return null;
  if (state === "running") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full border border-sky-400/50 bg-zinc-950 shadow-md" aria-label="Running">
        <Loader2 className="h-3 w-3 animate-spin text-sky-400" />
      </span>
    );
  }
  if (state === "succeeded") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full border border-emerald-400/50 bg-zinc-950 shadow-md" aria-label="Done">
        <CheckCircle2 className="h-3 w-3 text-emerald-400" />
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full border border-red-500/50 bg-zinc-950 shadow-md" aria-label="Failed">
        <XCircle className="h-3 w-3 text-red-400" />
      </span>
    );
  }
  return (
    <span className="flex h-5 w-5 items-center justify-center rounded-full border border-amber-400/50 bg-zinc-950 shadow-md" aria-label="Waiting for you">
      <CircleDot className="h-3 w-3 text-amber-400" />
    </span>
  );
}

/**
 * Agent Hub node: sleek compact rounded-2xl pill card in the center,
 * while its satellite connectors, tools, knowledge, and sub-agents render as
 * clean circular Make.com-style bubbles around it.
 */
function StepNodeView({ data, selected }: NodeProps<StepNodeType>) {
  const Icon = ICONS[data.type];
  const look = LOOKS[data.type];
  const hasProblems = data.problems.length > 0;
  const isRunning = data.state === "running" || data.state === "waiting";
  const brandName = data.type === "server" ? data.serverName || data.title : data.serverName;

  // Central AI Agent hub pill
  if (data.type === "agent") {
    return (
      <div
        className={cn(
          "animate-scale-in group relative w-60 overflow-hidden rounded-2xl border bg-[var(--surface-raised)] text-left shadow-xl shadow-black/50 transition-all duration-200 hover:-translate-y-0.5",
          hasProblems ? "border-red-500/70" : cn(look.ring, look.glow),
          selected && "ring-2 ring-[var(--accent-hover)] border-[var(--accent-hover)] shadow-[0_0_32px_-4px_rgba(99,102,241,0.55)]",
          data.state && STATE_RING[data.state],
        )}
        title={hasProblems ? data.problems.map((p) => p.message).join("\n") : undefined}
      >
        <div className={cn("h-1 w-full bg-gradient-to-r", look.bar)} aria-hidden />
        <Handle
          type="target"
          position={data.vertical ? Position.Top : Position.Left}
          className={cn("!h-2.5 !w-2.5 !border-2 !border-[var(--surface-raised)] transition-transform hover:scale-125", look.handle)}
        />
        <div className="flex items-center gap-3 p-3">
          <span className={cn("relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-md ring-1 ring-white/20", look.iconBg)}>
            {isRunning && <span aria-hidden className="absolute -inset-1 rounded-xl bg-indigo-400/30 blur-sm animate-pulse" />}
            <Icon className="relative h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <span className={cn("inline-flex items-center rounded-full border px-1.5 py-0 text-[9px] font-semibold uppercase tracking-wider", look.pill)}>
              {look.badge}
            </span>
            <p className="mt-0.5 truncate text-sm font-semibold text-zinc-100">{data.title}</p>
            <p className="truncate text-[11px] text-zinc-400">{data.subtitle}</p>
          </div>
          <StateBadge state={data.state} />
        </div>
        {data.detail && (
          <div className="border-t border-white/5 bg-sky-500/10 px-3 py-1.5 text-[11px] text-sky-300 flex items-center gap-1.5">
            {data.state === "running" && <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-sky-400" />}
            <span className="truncate">{data.detail}</span>
          </div>
        )}
        <Handle
          type="source"
          position={data.vertical ? Position.Bottom : Position.Right}
          className={cn("!h-2.5 !w-2.5 !border-2 !border-[var(--surface-raised)] transition-transform hover:scale-125", look.handle)}
        />
      </div>
    );
  }

  // Satellite nodes (Connector, Tool, Knowledge, Sub-agent): clean circular bubbles with label below
  return (
    <div
      className="animate-scale-in group relative flex w-40 flex-col items-center text-center select-none"
      title={hasProblems ? data.problems.map((p) => p.message).join("\n") : undefined}
    >
      <div className="relative flex items-center justify-center">
        {isRunning && (
          <span
            aria-hidden
            className={cn("pointer-events-none absolute -inset-1.5 rounded-full bg-gradient-to-tr opacity-55 blur-md animate-pulse", look.bar)}
          />
        )}

        {!NO_INPUT.includes(data.type) && (
          <Handle
            type="target"
            position={data.vertical ? Position.Top : Position.Left}
            className={cn("!h-2.5 !w-2.5 !border-2 !border-[var(--surface)] transition-transform hover:scale-125", look.handle)}
          />
        )}

        <div
          className={cn(
            "relative flex h-16 w-16 items-center justify-center rounded-full border-2 bg-[var(--surface-raised)] transition-all duration-200 group-hover:scale-105",
            hasProblems ? "border-red-500/80 shadow-[0_0_20px_-4px_rgba(239,68,68,0.45)]" : cn(look.ring, look.glow),
            selected && "ring-4 ring-[var(--accent-hover)]/45 border-[var(--accent-hover)] scale-105",
            data.state && STATE_RING[data.state],
          )}
        >
          <span aria-hidden className={cn("pointer-events-none absolute inset-1 rounded-full bg-gradient-to-b opacity-15", look.bar)} />

          {brandName && data.type === "server" ? (
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/95 p-1.5 shadow-inner ring-1 ring-white/20">
              <ConnectorIcon name={brandName} size="sm" className="h-6 w-6 bg-transparent p-0" />
            </div>
          ) : (
            <span className={cn("flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br shadow-inner ring-1 ring-white/20", look.iconBg)}>
              <Icon className="h-4 w-4" />
            </span>
          )}

          {data.state && data.state !== "skipped" && (
            <span className="absolute -right-1 -top-1">
              <StateBadge state={data.state} />
            </span>
          )}

          {hasProblems && (
            <span className="absolute -left-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full border border-red-500/50 bg-zinc-950 px-1 text-[10px] font-bold text-red-400 shadow-md">
              <AlertTriangle className="h-3 w-3" />
            </span>
          )}
        </div>

        {data.type !== "output" && (
          <Handle
            type="source"
            position={data.vertical ? Position.Bottom : Position.Right}
            className={cn("!h-2.5 !w-2.5 !border-2 !border-[var(--surface)] transition-transform hover:scale-125", look.handle)}
          />
        )}
      </div>

      {/* Label & 1-line subtitle underneath the bubble */}
      <div className="mt-1.5 flex w-full flex-col items-center px-1">
        <p className="max-w-[152px] truncate text-xs font-semibold text-zinc-100 group-hover:text-white transition-colors">
          {data.title}
        </p>
        <p className="mt-0.5 max-w-[152px] truncate text-[10px] text-zinc-400" title={data.subtitle}>
          {data.subtitle}
        </p>
        {data.detail && (
          <span className="mt-1 inline-flex max-w-[152px] items-center gap-1 truncate rounded-full border border-sky-400/30 bg-sky-500/15 px-2 py-0.5 text-[10px] text-sky-300">
            {data.state === "running" && <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-sky-400" />}
            <span className="truncate">{data.detail}</span>
          </span>
        )}
        {data.connect && (
          <div className="nodrag mt-1.5 flex justify-center" onClick={(e) => e.stopPropagation()}>
            <ConnectButton
              serverId={data.connect.serverId}
              serverName={data.connect.serverName}
              token={data.connect.token}
              className="rounded-full px-2.5 py-0.5 text-[11px]"
            />
          </div>
        )}
      </div>
    </div>
  );
}

export const StepNode = memo(StepNodeView);
export const nodeTypes = { step: StepNode };

type Size = { width: number; height: number };

/**
 * The canvases are controlled and rebuild their nodes on every run event. A
 * node handed back without its measured size is hidden until re-measured
 * (which never happens if it didn't resize), and the minimap skips it — so
 * remember the sizes React Flow reports and pass them back as ``measured``.
 */
export function useNodeSizes() {
  const [sizes, setSizes] = useState<Record<string, Size>>({});
  const track = useCallback((changes: NodeChange[]) => {
    const measured = changes.filter((c) => c.type === "dimensions" && c.dimensions);
    if (!measured.length) return;
    setSizes((prev) => {
      const next = { ...prev };
      for (const c of measured) if (c.type === "dimensions" && c.dimensions) next[c.id] = c.dimensions;
      return next;
    });
  }, []);
  return { sizes, track };
}
