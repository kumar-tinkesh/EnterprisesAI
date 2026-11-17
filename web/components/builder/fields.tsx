"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/** Small form pieces shared by the builder panels. */

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium text-zinc-700">{label}</span>
      {children}
      {hint && <span className="block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus-visible:outline-none focus-visible:border-[var(--accent-hover)] focus-visible:ring-2 focus-visible:ring-[var(--accent-wash-strong)]",
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
        "h-9 w-full rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 text-sm text-[var(--text)] focus-visible:outline-none focus-visible:border-[var(--accent-hover)] focus-visible:ring-2 focus-visible:ring-[var(--accent-wash-strong)]",
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

/** An on/off switch (the step popup's Override). */
export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={cn(
        "relative inline-flex h-4 w-7 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-indigo-600" : "bg-zinc-300",
      )}
    >
      <span className={cn("inline-block h-3 w-3 rounded-full bg-white shadow transition-transform", checked ? "translate-x-3.5" : "translate-x-0.5")} />
    </button>
  );
}

/** Set by a workflow step's popup: each setting gets its own switch, and only
 *  settings switched on are the step's own (the rest are the agent's). */
export const OverrideParams = React.createContext<{ isOn: (key: string) => boolean; toggle: (key: string, on: boolean) => void } | null>(null);

/** One setting. Normally a plain field; inside ``OverrideParams`` a card with
 *  its name and a switch, showing the control only while switched on. */
export function Param({ k, label, hint, children }: { k: string; label: string; hint?: string; children: React.ReactNode }) {
  const params = React.useContext(OverrideParams);
  if (!params) return <Field label={label} hint={hint}>{children}</Field>;
  const on = params.isOn(k);
  return (
    <div className="rounded-lg border border-zinc-200 bg-white px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className={cn("text-xs font-medium", on ? "text-zinc-900" : "text-zinc-600")}>{label}</span>
        <Switch label={`Override ${label} for this step`} checked={on} onChange={(v) => params.toggle(k, v)} />
      </div>
      {on && (
        <div className="mt-2">{children}</div>
      )}
    </div>
  );
}

/** An on/off setting: a checkbox normally, an On/Off choice as a step override. */
export function BoolParam({ k, label, checked, onChange }: { k: string; label: string; checked: boolean; onChange: (v: boolean) => void }) {
  const params = React.useContext(OverrideParams);
  if (!params) return <Toggle label={label} checked={checked} onChange={onChange} />;
  return (
    <Param k={k} label={label}>
      <div className="flex gap-1">
        {([true, false] as const).map((v) => (
          <button
            key={String(v)}
            type="button"
            onClick={() => onChange(v)}
            className={cn("rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer", checked === v ? "bg-indigo-600 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200")}
          >
            {v ? "On" : "Off"}
          </button>
        ))}
      </div>
    </Param>
  );
}

/** Two fields side by side (stacked when each is a step-override card). */
export function Pair({ children }: { children: React.ReactNode }) {
  const params = React.useContext(OverrideParams);
  return <div className={params ? "space-y-2" : "grid grid-cols-2 gap-2"}>{children}</div>;
}

/** Inside a provider set to true, sections drop their own heading and padding —
 *  for hosts (the guided agent setup) that put each section in their own card. */
export const BareSections = React.createContext(false);

export function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  const bare = React.useContext(BareSections);
  if (bare) {
    return (
      <div className="space-y-3">
        {action && <div className="flex justify-end">{action}</div>}
        {children}
      </div>
    );
  }
  return (
    <section className="space-y-3 border-b border-zinc-100 px-3.5 py-3.5 last:border-0">
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
  return <span className={cn("rounded px-1.5 py-0.5 text-xs font-semibold uppercase", tone)}>{risk}</span>;
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
      {error && <p className="text-xs text-red-600">Not valid JSON yet: {error}</p>}
    </div>
  );
}
