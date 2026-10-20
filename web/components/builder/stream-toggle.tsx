"use client";

import { Zap } from "lucide-react";

import { useStreamPref } from "@/lib/builder/stream-pref";
import { cn } from "@/lib/utils";

/** "Stream" on/off: watch the answer being written, or get it whole. */
export function StreamToggle({ className }: { className?: string }) {
  const [on, setOn] = useStreamPref();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => setOn(!on)}
      title={on ? "Answers appear as they're written. Click to get them whole." : "Answers appear when they're done. Click to watch them being written."}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium cursor-pointer",
        on ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-zinc-200 text-zinc-500 hover:text-zinc-800",
        className,
      )}
    >
      <Zap className={cn("h-3 w-3", on && "fill-current")} /> Stream {on ? "on" : "off"}
    </button>
  );
}
