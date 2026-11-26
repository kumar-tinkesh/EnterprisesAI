"use client";

import { memo, useState } from "react";
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

export type FlowEdgeData = {
  /** A line out of a condition: the branch it stands for. */
  branch?: string | null;
  /** Human-readable route label shown on hover ("Source → Target"). */
  routeLabel?: string;
  /** Y coordinate of a clean bypass rail when the direct path crosses intermediate nodes. */
  detourY?: number;
  /** True when another node/edge is hovered or selected and this edge is unrelated. */
  dimmed?: boolean;
  /** True when connected to the hovered or selected node. */
  highlighted?: boolean;
  /** Notifies parent when the user hovers/leaves this edge. */
  onHoverChange?: (id: string | null) => void;
  /** Remove the line (absent when it can't be edited). */
  onDelete?: (id: string) => void;
};
export type FlowEdgeType = Edge<FlowEdgeData, "flow">;

function branchTone(branch: string): string {
  const b = branch.trim().toLowerCase();
  if (/^(true|yes|pass|passed|ok|approved|match|success)/.test(b)) {
    return "border-emerald-400/40 bg-emerald-950/90 text-emerald-300";
  }
  if (/^(false|no|fail|failed|reject|rejected|else|error|deny)/.test(b)) {
    return "border-rose-400/40 bg-rose-950/90 text-rose-300";
  }
  return "border-amber-400/40 bg-zinc-900/95 text-amber-200";
}

function buildDetourPath(sourceX: number, sourceY: number, targetX: number, targetY: number, detourY: number): [string, number, number] {
  const lead = 28;
  const x1 = sourceX + lead;
  const x2 = targetX - lead;
  const sDir = detourY < sourceY ? -1 : 1;
  const tDir = targetY < detourY ? -1 : 1;
  const r1 = Math.min(18, Math.abs(detourY - sourceY) / 2, (x2 - x1) / 4);
  const r2 = Math.min(18, Math.abs(targetY - detourY) / 2, (x2 - x1) / 4);

  const path = [
    `M ${sourceX} ${sourceY}`,
    `L ${x1 - r1} ${sourceY}`,
    `Q ${x1} ${sourceY} ${x1} ${sourceY + sDir * r1}`,
    `L ${x1} ${detourY - sDir * r1}`,
    `Q ${x1} ${detourY} ${x1 + r1} ${detourY}`,
    `L ${x2 - r2} ${detourY}`,
    `Q ${x2} ${detourY} ${x2} ${detourY + tDir * r2}`,
    `L ${x2} ${targetY - tDir * r2}`,
    `Q ${x2} ${targetY} ${x2 + r2} ${targetY}`,
    `L ${targetX} ${targetY}`,
  ].join(" ");

  return [path, (sourceX + targetX) / 2, detourY];
}

/** A line between steps: clean routing around obstacles, focus highlight on hover/select, branch name, and × remove. */
function FlowEdgeView({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, selected, data }: EdgeProps<FlowEdgeType>) {
  const [hover, setHover] = useState(false);
  const useDetour = typeof data?.detourY === "number" && targetX - sourceX > 120 && Math.abs(data.detourY - sourceY) >= 24 && Math.abs(targetY - data.detourY) >= 24;
  const [path, x, y] = useDetour
    ? buildDetourPath(sourceX, sourceY, targetX, targetY, data!.detourY!)
    : getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 14 });

  const active = hover || !!selected || !!data?.highlighted;
  const removable = !!data?.onDelete && (hover || selected);
  const showLabel = !!data?.branch || removable || (hover && !!data?.routeLabel);

  const enter = () => {
    setHover(true);
    data?.onHoverChange?.(id);
  };
  const leave = () => {
    setHover(false);
    data?.onHoverChange?.(null);
  };

  const edgeStyle = {
    ...style,
    opacity: data?.dimmed && !active ? 0.14 : active ? 1 : (style?.opacity ?? 0.85),
    strokeWidth: active ? 2.85 : (style?.strokeWidth ?? 2),
    filter: active ? "drop-shadow(0 0 6px rgba(99,102,241,0.55))" : undefined,
    transition: "opacity 160ms ease, stroke-width 160ms ease",
  };

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={edgeStyle} />
      {/* A wide invisible line: easy to hover. */}
      <path d={path} fill="none" stroke="transparent" strokeWidth={18} onMouseEnter={enter} onMouseLeave={leave} />
      {showLabel && (
        <EdgeLabelRenderer>
          <div
            className={cn(
              "nodrag nopan pointer-events-auto absolute flex items-center gap-1 transition-opacity duration-150",
              data?.dimmed && !active && "opacity-20",
            )}
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
            onMouseEnter={enter}
            onMouseLeave={leave}
          >
            {data?.branch && (
              <span className={cn("rounded-full border px-2 py-0.5 text-xs font-semibold shadow-sm backdrop-blur-xs", branchTone(data.branch))}>
                {data.branch}
              </span>
            )}
            {hover && data?.routeLabel && (
              <span className="rounded-full border border-white/15 bg-zinc-900/95 px-2 py-0.5 text-[10px] font-medium text-zinc-200 shadow-md backdrop-blur-xs whitespace-nowrap">
                {data.routeLabel}
              </span>
            )}
            {removable && (
              <button
                type="button"
                aria-label="Remove line"
                title="Remove line"
                onClick={(e) => {
                  e.stopPropagation();
                  data!.onDelete!(id);
                }}
                className="animate-scale-in flex h-5 w-5 items-center justify-center rounded-full border border-white/15 bg-zinc-900 text-zinc-300 shadow cursor-pointer transition-colors hover:border-red-400/60 hover:bg-red-500/20 hover:text-red-200"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const FlowEdge = memo(FlowEdgeView);
export const flowEdgeTypes = { flow: FlowEdge };
