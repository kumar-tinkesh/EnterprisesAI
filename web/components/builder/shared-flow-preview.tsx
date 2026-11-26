"use client";

import { useEffect, useMemo, useState } from "react";
import {
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
  Pause,
  Play,
  PlayCircle,
  Send,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";

import { ConnectorIcon } from "@/components/connections/connector-icon";
import type { SharedOutline, SharedStep } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

type VisualStatus = "idle" | "pending" | "running" | "succeeded" | "failed" | "waiting" | "skipped";

type VisualNode = {
  id: string;
  title: string;
  kind: string;
  hint?: string;
  apps: string[];
  level: number;
  status: VisualStatus;
  x: number;
  y: number;
  isHub?: boolean;
};

type VisualEdge = {
  id: string;
  from: VisualNode;
  to: VisualNode;
  active: boolean;
  done: boolean;
};

const KIND_LOOK: Record<string, { Icon: typeof Bot; head: string; ring: string }> = {
  input: { Icon: LogIn, head: "from-sky-400 to-sky-600", ring: "border-sky-400/50" },
  manual_trigger: { Icon: PlayCircle, head: "from-blue-500 to-indigo-600", ring: "border-blue-400/50" },
  schedule_trigger: { Icon: CalendarClock, head: "from-teal-400 to-teal-600", ring: "border-teal-400/50" },
  agent: { Icon: Bot, head: "from-indigo-500 to-violet-600", ring: "border-indigo-400/55" },
  tool: { Icon: Wrench, head: "from-orange-400 to-amber-600", ring: "border-orange-400/50" },
  app: { Icon: Wrench, head: "from-indigo-400 to-sky-500", ring: "border-sky-400/45" },
  condition: { Icon: GitBranch, head: "from-amber-400 to-amber-600", ring: "border-amber-400/50" },
  join: { Icon: Merge, head: "from-slate-400 to-slate-600", ring: "border-slate-400/45" },
  human_approval: { Icon: Hand, head: "from-rose-400 to-rose-600", ring: "border-rose-400/50" },
  output: { Icon: Send, head: "from-emerald-400 to-emerald-600", ring: "border-emerald-400/50" },
  code: { Icon: Code2, head: "from-zinc-500 to-zinc-700", ring: "border-zinc-400/45" },
};

function statusFor(simStage: number, nodeLevel: number, maxLevel: number, live?: SharedStep["status"]): VisualStatus {
  if (live) return live;
  if (simStage > maxLevel) return "succeeded";
  if (nodeLevel < simStage) return "succeeded";
  if (nodeLevel === simStage) return "running";
  return "idle";
}

function cubicPath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.max(36, (x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

/**
 * Animated canvas-style preview for shared/published agents & workflows.
 * Safely renders only public step titles, kinds, parallel levels, and app icons—never private instructions.
 */
export function SharedFlowPreview({
  kind,
  name,
  outline,
  liveSteps,
  running = false,
  compact = false,
  className,
}: {
  kind: "agent" | "workflow";
  name: string;
  outline?: SharedOutline | null;
  liveSteps?: SharedStep[];
  running?: boolean;
  compact?: boolean;
  className?: string;
}) {
  const hasLive = !!liveSteps?.length;
  const [playing, setPlaying] = useState(true);
  const [simStage, setSimStage] = useState(0);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const { nodes, edges, width, height, maxLevel } = useMemo(() => {
    const colGap = compact ? 156 : 184;
    const rowGap = compact ? 92 : 106;
    const orbCenterOffset = compact ? 24 : 28; // half of h-12 (48px) / h-14 (56px)
    const padX = compact ? 56 : 68;
    const padY = compact ? 34 : 42;

    const outlineById = new Map((outline?.steps ?? []).map((s) => [s.id, s]));
    const liveById = new Map((liveSteps ?? []).map((s) => [s.id, s]));

    // Build unified ordered step list.
    const rawSteps = (outline?.steps?.length
      ? outline.steps
      : (liveSteps ?? []).map((s, idx) => ({
          id: s.id,
          title: s.title,
          kind: s.kind,
          hint: "",
          apps: [] as string[],
          level: idx,
        })));

    // Single agent view: Agent Hub on the left -> connected Apps / Reasoning on the right.
    const uniqueApps = Array.from(new Set([...(outline?.apps ?? []), ...rawSteps.flatMap((s) => s.apps)]));
    if (kind === "agent" && rawSteps.length <= 1) {
      const liveAgentStatus = liveSteps?.[0]?.status;
      const targets = uniqueApps.length
        ? uniqueApps.map((app, i) => ({
            id: `app-${i}`,
            title: app,
            kind: "app",
            hint: `Connected ${app} tools`,
            apps: [app],
          }))
        : [
            {
              id: "answer",
              title: "AI Answer",
              kind: "output",
              hint: "Analyzes your prompt and replies directly",
              apps: [] as string[],
            },
          ];

      const totalRows = targets.length;
      const h = Math.max(compact ? 148 : 176, padY * 2 + (totalRows - 1) * rowGap + 56);
      const midY = h / 2 - orbCenterOffset;
      const w = padX * 2 + colGap + 120;

      const hub: VisualNode = {
        id: rawSteps[0]?.id ?? "agent-hub",
        title: name || rawSteps[0]?.title || "AI Agent",
        kind: "agent",
        hint: rawSteps[0]?.hint || "Understands your request and picks the right tools",
        apps: uniqueApps,
        level: 0,
        status: statusFor(simStage, 0, 1, liveAgentStatus),
        x: padX,
        y: midY,
        isHub: true,
      };

      const targetNodes: VisualNode[] = targets.map((t, i) => {
        const y = midY + (i - (totalRows - 1) / 2) * rowGap;
        const simActive = !hasLive && simStage === 1;
        const status: VisualStatus = hasLive
          ? liveAgentStatus === "running"
            ? "running"
            : liveAgentStatus === "succeeded"
              ? "succeeded"
              : liveAgentStatus === "failed"
                ? "failed"
                : "idle"
          : simActive
            ? "running"
            : simStage > 1
              ? "succeeded"
              : "idle";
        return {
          ...t,
          level: 1,
          status,
          x: padX + colGap + 12,
          y,
        };
      });

      const allNodes = [hub, ...targetNodes];
      const allEdges: VisualEdge[] = targetNodes.map((t) => ({
        id: `${hub.id}->${t.id}`,
        from: hub,
        to: t,
        active: (!hasLive && simStage === 1) || (hasLive && liveAgentStatus === "running"),
        done: (!hasLive && simStage > 1) || (hasLive && liveAgentStatus === "succeeded"),
      }));
      return { nodes: allNodes, edges: allEdges, width: w, height: h, maxLevel: 1 };
    }

    // Multi-step / workflow view grouped left-to-right by level.
    const levels = [...new Set(rawSteps.map((s) => s.level))].sort((a, b) => a - b);
    const maxLvl = Math.max(levels.length - 1, 0);
    const maxCount = Math.max(1, ...levels.map((lvl) => rawSteps.filter((s) => s.level === lvl).length));
    const h = Math.max(compact ? 156 : 186, padY * 2 + (maxCount - 1) * rowGap + 56);
    const w = Math.max(340, padX * 2 + Math.max(1, levels.length - 1) * colGap + 96);
    const centerY = h / 2 - orbCenterOffset;

    const byCol: VisualNode[][] = levels.map((lvl, colIdx) => {
      const group = rawSteps.filter((s) => s.level === lvl);
      return group.map((s, rowIdx) => {
        const live = liveById.get(s.id)?.status;
        const meta = outlineById.get(s.id);
        return {
          id: s.id,
          title: s.title,
          kind: s.kind,
          hint: meta?.hint || s.hint,
          apps: meta?.apps ?? s.apps,
          level: colIdx,
          status: statusFor(simStage, colIdx, maxLvl, live),
          x: padX + colIdx * colGap,
          y: centerY + (rowIdx - (group.length - 1) / 2) * rowGap,
        };
      });
    });

    const builtEdges: VisualEdge[] = [];
    for (let c = 0; c < byCol.length - 1; c++) {
      const srcCol = byCol[c];
      const tgtCol = byCol[c + 1];
      for (const s of srcCol) {
        for (const t of tgtCol) {
          const active =
            hasLive
              ? (s.status === "succeeded" || s.status === "running") && t.status === "running"
              : simStage === c + 1;
          const done =
            hasLive
              ? s.status === "succeeded" && (t.status === "succeeded" || t.status === "waiting")
              : simStage > c + 1;
          builtEdges.push({ id: `${s.id}->${t.id}`, from: s, to: t, active, done });
        }
      }
    }

    return {
      nodes: byCol.flat(),
      edges: builtEdges,
      width: w,
      height: h,
      maxLevel: maxLvl,
    };
  }, [outline, liveSteps, kind, name, simStage, hasLive, compact]);

  // Smooth auto-looping animation in outline / simulation mode.
  useEffect(() => {
    if (hasLive || !playing || nodes.length === 0) return;
    const totalStages = maxLevel + 2; // 0..maxLevel active, maxLevel+1 all done brief pause
    const id = setInterval(() => {
      setSimStage((s) => (s + 1) % totalStages);
    }, 1350);
    return () => clearInterval(id);
  }, [hasLive, playing, maxLevel, nodes.length]);

  if (nodes.length === 0) return null;

  const orbSize = compact ? 48 : 56;
  const orbRadius = orbSize / 2;
  const hoveredNode = nodes.find((n) => n.id === hoveredId) ?? null;

  return (
    <div className={cn("overflow-hidden rounded-2xl border border-white/10 bg-[#0d0d11]/90 shadow-lg", className)}>
      {/* Top status / control bar */}
      <div className="flex items-center justify-between gap-2 border-b border-white/10 bg-white/[0.02] px-3.5 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-indigo-500/20 text-indigo-300">
            <Sparkles className="h-3 w-3" />
          </span>
          <span className="truncate text-xs font-medium text-zinc-200">
            {hasLive ? (running ? "Live execution flow" : "Last run flow") : "How it works · Interactive flow"}
          </span>
          {!hasLive && (
            <span className="hidden rounded-full border border-sky-400/25 bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-300 sm:inline-block">
              {simStage > maxLevel ? "Complete" : `Stage ${Math.min(simStage + 1, maxLevel + 1)} of ${maxLevel + 1}`}
            </span>
          )}
        </div>
        {!hasLive && (
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5 text-[11px] font-medium text-zinc-300 transition-colors hover:border-white/20 hover:bg-white/[0.08] hover:text-white cursor-pointer"
          >
            {playing ? <><Pause className="h-3 w-3" /> Pause</> : <><Play className="h-3 w-3" /> Animate</>}
          </button>
        )}
      </div>

      {/* Scrollable canvas stage with dot grid background */}
      <div
        className="relative overflow-x-auto overflow-y-hidden"
        style={{
          backgroundImage: "radial-gradient(rgba(255,255,255,0.08) 1px, transparent 1px)",
          backgroundSize: "18px 18px",
        }}
      >
        <div className="relative mx-auto" style={{ width, height }}>
          {/* Connecting SVG paths & animated data packets */}
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${width} ${height}`}>
            {edges.map((edge) => {
              const x1 = edge.from.x + orbRadius;
              const y1 = edge.from.y + orbRadius;
              const x2 = edge.to.x - orbRadius;
              const y2 = edge.to.y + orbRadius;
              const path = cubicPath(x1, y1, x2, y2);
              const stroke = edge.active ? "#38bdf8" : edge.done ? "#34d399" : "#6366f1";
              return (
                <g key={edge.id}>
                  <path
                    d={path}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={edge.active ? 2.4 : 1.75}
                    strokeOpacity={edge.active || edge.done ? 0.95 : 0.4}
                    strokeDasharray={edge.active ? "6 4" : undefined}
                  >
                    {edge.active && (
                      <animate attributeName="stroke-dashoffset" from="20" to="0" dur="0.8s" repeatCount="indefinite" />
                    )}
                  </path>
                  {edge.active && (
                    <g>
                      <circle r="5.5" fill="#38bdf8" opacity="0.3">
                        <animateMotion dur="1.05s" repeatCount="indefinite" path={path} />
                      </circle>
                      <circle r="2.8" fill="#e0f2fe">
                        <animateMotion dur="1.05s" repeatCount="indefinite" path={path} />
                      </circle>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>

          {/* Circular nodes (or Hub for agent) */}
          {nodes.map((node) => {
            const look = KIND_LOOK[node.kind] ?? KIND_LOOK.agent;
            const Icon = look.Icon;
            const isRunning = node.status === "running";
            const isDone = node.status === "succeeded";
            const isFailed = node.status === "failed";
            const isWaiting = node.status === "waiting";
            const isSkipped = node.status === "skipped";
            const primaryApp = node.apps[0];

            return (
              <div
                key={node.id}
                onMouseEnter={() => setHoveredId(node.id)}
                onMouseLeave={() => setHoveredId((cur) => (cur === node.id ? null : cur))}
                style={{
                  left: node.x,
                  top: node.y,
                  transform: "translate(-50%, 0)",
                }}
                className={cn(
                  "absolute flex w-32 flex-col items-center text-center transition-opacity duration-200 select-none",
                  isSkipped && "opacity-45",
                )}
              >
                <div className="relative flex items-center justify-center">
                  {isRunning && (
                    <span
                      aria-hidden
                      className={cn("pointer-events-none absolute -inset-1.5 rounded-full bg-gradient-to-tr opacity-60 blur-md animate-pulse", look.head)}
                    />
                  )}
                  <div
                    style={{ width: orbSize, height: orbSize }}
                    className={cn(
                      "relative flex items-center justify-center rounded-full border-2 bg-[#16161b] transition-all duration-300",
                      isRunning
                        ? "border-sky-400 scale-105 shadow-[0_0_22px_-3px_rgba(56,189,248,0.65)]"
                        : isDone
                          ? "border-emerald-400/75 shadow-[0_0_16px_-4px_rgba(52,211,153,0.45)]"
                          : isFailed
                            ? "border-red-500/80 shadow-[0_0_16px_-4px_rgba(239,68,68,0.45)]"
                            : isWaiting
                              ? "border-amber-400/75"
                              : look.ring,
                    )}
                  >
                    {primaryApp && !node.isHub ? (
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white/95 p-1.5 shadow-inner">
                        <ConnectorIcon name={primaryApp} size="sm" className="h-5 w-5 bg-transparent p-0" />
                      </div>
                    ) : (
                      <span
                        className={cn(
                          "flex items-center justify-center rounded-full bg-gradient-to-br text-white shadow-inner ring-1 ring-white/20",
                          compact ? "h-8 w-8" : "h-9 w-9",
                          look.head,
                        )}
                      >
                        <Icon className={compact ? "h-4 w-4" : "h-[18px] w-[18px]"} />
                      </span>
                    )}

                    {/* Mini status badge */}
                    {isRunning && (
                      <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-sky-400/50 bg-zinc-950 shadow">
                        <Loader2 className="h-3 w-3 animate-spin text-sky-400" />
                      </span>
                    )}
                    {isDone && (
                      <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-emerald-400/50 bg-zinc-950 shadow">
                        <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                      </span>
                    )}
                    {isFailed && (
                      <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-red-500/50 bg-zinc-950 shadow">
                        <XCircle className="h-3 w-3 text-red-400" />
                      </span>
                    )}
                    {isWaiting && (
                      <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-amber-400/50 bg-zinc-950 shadow">
                        <CircleDot className="h-3 w-3 text-amber-400" />
                      </span>
                    )}
                  </div>
                </div>

                <p className="mt-1.5 max-w-[120px] truncate text-[11px] font-semibold text-zinc-100" title={node.title}>
                  {node.title}
                </p>
                {node.apps.length > 0 && !node.isHub && (
                  <p className="max-w-[120px] truncate text-[10px] text-zinc-400">{node.apps.join(", ")}</p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Hover detail footer (shows hovered step description safely) */}
      {(hoveredNode?.hint || hoveredNode?.apps.length) && (
        <div className="flex items-center gap-2 border-t border-white/10 bg-white/[0.02] px-3.5 py-1.5 text-[11px] text-zinc-400">
          <span className="font-medium text-zinc-200">{hoveredNode.title}:</span>
          <span className="min-w-0 flex-1 truncate">{hoveredNode.hint || `Uses ${hoveredNode.apps.join(", ")}`}</span>
        </div>
      )}
    </div>
  );
}
