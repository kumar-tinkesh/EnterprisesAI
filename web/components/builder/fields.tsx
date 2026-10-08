"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/** Small form pieces shared by the builder panels. */

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-zinc-700">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-zinc-400">{hint}</span>}
    </label>
  );
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm placeholder:text-zinc-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 w-full rounded-md border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900",
        className,
      )}
      {...props}
    />
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-700">
      <input type="checkbox" className="h-4 w-4 accent-indigo-600" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="space-y-3 border-b border-zinc-100 px-4 py-4 last:border-0">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const tone = risk === "read" ? "bg-emerald-50 text-emerald-700" : risk === "delete" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700";
  return <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", tone)}>{risk}</span>;
}

/** JSON object editor: shows text, reports parse errors, calls back with the object. */
export function JsonField({
  value,
  onChange,
  rows = 4,
  placeholder = "{}",
}: {
  value: Record<string, unknown> | null | undefined;
  onChange: (v: Record<string, unknown> | null) => void;
  rows?: number;
  placeholder?: string;
}) {
  const [text, setText] = React.useState(() => (value && Object.keys(value).length ? JSON.stringify(value, null, 2) : ""));
  const [error, setError] = React.useState<string | null>(null);
  return (
    <div className="space-y-1">
      <Textarea
        rows={rows}
        className="font-mono text-xs"
        placeholder={placeholder}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) {
            setError(null);
            onChange(null);
            return;
          }
          try {
            const parsed = JSON.parse(e.target.value);
            if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("must be an object");
            setError(null);
            onChange(parsed);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Invalid JSON");
          }
        }}
      />
      {error && <p className="text-[11px] text-red-600">Not valid JSON yet: {error}</p>}
    </div>
  );
}
