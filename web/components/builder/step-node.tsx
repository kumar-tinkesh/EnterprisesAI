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
  GitBranch,
  Hand,
  Loader2,
  LogIn,
  Merge,
  PlayCircle,
  Send,
  Wrench,
  XCircle,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { StepState } from "@/lib/builder/run-state";
import type { NodeType, Problem } from "@/lib/builder/types";

/** "knowledge" only appears on the agent-mode canvas (a knowledge base feeding the agent). */
export type StepKind = NodeType | "knowledge";

export type StepData = {
  type: StepKind;
  title: string;
  subtitle: string;
  problems: Problem[];
  state?: StepState;
  detail?: string | null;
};

export type StepNodeType = Node<StepData, "step">;

const ICONS: Record<StepKind, typeof Bot> = {
  knowledge: BookOpen,
  input: LogIn,
  manual_trigger: PlayCircle,
  schedule_trigger: CalendarClock,
  agent: Bot,
  tool: Wrench,
  condition: GitBranch,
  join: Merge,
  human_approval: Hand,
  output: Send,
};

// Literal class names so Tailwind keeps them.
const TONES: Record<StepKind, string> = {
  knowledge: "bg-violet-50 text-violet-700",
  input: "bg-sky-50 text-sky-700",
  manual_trigger: "bg-sky-50 text-sky-700",
  schedule_trigger: "bg-sky-50 text-sky-700",
  agent: "bg-indigo-50 text-indigo-700",
  tool: "bg-emerald-50 text-emerald-700",
  condition: "bg-amber-50 text-amber-700",
  join: "bg-violet-50 text-violet-700",
  human_approval: "bg-rose-50 text-rose-700",
  output: "bg-zinc-100 text-zinc-700",
};

const STATE_RING: Record<StepState, string> = {
  running: "ring-2 ring-sky-400 shadow-sky-200 shadow-lg animate-pulse",
  succeeded: "ring-2 ring-emerald-400",
  failed: "ring-2 ring-red-400",
  waiting: "ring-2 ring-amber-400 animate-pulse",
  skipped: "opacity-50",
};

const NO_INPUT: StepKind[] = ["input", "manual_trigger", "schedule_trigger", "knowledge"];

function StateIcon({ state }: { state?: StepState }) {
  if (state === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-500" aria-label="Running" />;
  if (state === "succeeded") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-label="Done" />;
  if (state === "failed") return <XCircle className="h-3.5 w-3.5 text-red-500" aria-label="Failed" />;
  if (state === "waiting") return <CircleDot className="h-3.5 w-3.5 text-amber-500" aria-label="Waiting for you" />;
  return null;
}

function StepNodeView({ data, selected }: NodeProps<StepNodeType>) {
  const Icon = ICONS[data.type];
  const hasProblems = data.problems.length > 0;
  return (
    <div
      className={cn(
        "w-60 rounded-xl border bg-white px-3 py-2.5 text-left shadow-sm transition-shadow",
        selected ? "border-indigo-500 shadow-md" : hasProblems ? "border-red-300" : "border-zinc-200",
        data.state && STATE_RING[data.state],
      )}
      title={hasProblems ? data.problems.map((p) => p.message).join("\n") : undefined}
    >
      {!NO_INPUT.includes(data.type) && <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-2 !border-white !bg-zinc-400" />}
      <div className="flex items-center gap-2">
        <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", TONES[data.type])}>
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-zinc-900">{data.title}</p>
          <p className="truncate text-[11px] text-zinc-500">{data.subtitle}</p>
        </div>
        <StateIcon state={data.state} />
        {hasProblems && (
          <span className="flex items-center gap-0.5 rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-600">
            <AlertTriangle className="h-3 w-3" />
            {data.problems.length}
          </span>
        )}
      </div>
      {data.detail && <p className="mt-1.5 truncate rounded bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-700">{data.detail}</p>}
      {data.type !== "output" && <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-2 !border-white !bg-zinc-400" />}
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
