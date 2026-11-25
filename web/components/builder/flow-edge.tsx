"use client";

import { memo, useState } from "react";
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

export type FlowEdgeData = {
  /** A line out of a condition: the branch it stands for. */
  branch?: string | null;
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

/** A line between steps: its branch name (out of a condition) and, on hover or when selected, × to remove it. */
function FlowEdgeView({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, selected, data }: EdgeProps<FlowEdgeType>) {
  const [hover, setHover] = useState(false);
  const [path, x, y] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const removable = !!data?.onDelete && (hover || selected);
  const edgeStyle = hover || selected ? { ...style, strokeWidth: 2.75, filter: "drop-shadow(0 0 6px rgba(99,102,241,0.55))" } : style;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={edgeStyle} />
      {/* A wide invisible line: easy to hover. */}
      <path d={path} fill="none" stroke="transparent" strokeWidth={18} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} />
      {(data?.branch || removable) && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-auto absolute flex items-center gap-1"
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
          >
            {data?.branch && (
              <span className={cn("rounded-full border px-2 py-0.5 text-xs font-semibold shadow-sm backdrop-blur-xs", branchTone(data.branch))}>
                {data.branch}
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
