"use client";

import { cn } from "@/lib/utils";

/** Underlined tabs; the row scrolls sideways on a narrow screen instead of wrapping. */
export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: readonly (readonly [T, string])[] }) {
  return (
    <div className="no-scrollbar flex gap-1 overflow-x-auto border-b border-zinc-200" role="tablist">
      {tabs.map(([id, label]) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={value === id}
          onClick={() => onChange(id)}
          className={cn(
            "-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors cursor-pointer",
            value === id ? "border-[var(--accent-hover)] text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-900",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
