"use client";

import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { Check, ChevronDown, Sparkles, type LucideIcon } from "lucide-react";

import { builderApi } from "@/lib/builder/api";
import { WIZARD_STEPS, type WizardStepId } from "@/lib/builder/agent-wizard";
import type { AgentInsights, AgentProfile, DraftAgent, Risk, ToolCandidate } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

/** What every step after Describe works with. */
export interface StepProps {
  token: string;
  draft: DraftAgent;
  update: (next: DraftAgent) => void;
  insights: AgentInsights | null;
  toolMeta: Record<string, ToolCandidate>;
  /** Remember what we know about tools added along the way (name, server, risk). */
  addMeta: (tools: ToolCandidate[]) => void;
  servers: Record<string, ServerInfo>;
  profiles: AgentProfile[];
  goTo: (step: WizardStepId) => void;
  /** Open the connect dialog for one server. */
  connect: (serverId: string) => void;
}

/** Literal class names so Tailwind keeps them (and .builder-dark remaps them). */
const TONES = {
  indigo: "bg-indigo-50 text-indigo-700",
  emerald: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
  violet: "bg-violet-50 text-violet-700",
  sky: "bg-sky-50 text-sky-700",
  rose: "bg-rose-50 text-rose-700",
  zinc: "bg-zinc-100 text-zinc-700",
} as const;

/** One category of settings: a card with an icon, a one-line "what this is", and a body that folds away. */
export function Category({
  icon: Icon,
  title,
  hint,
  tone = "indigo",
  badge,
  action,
  defaultOpen = true,
  children,
}: {
  icon: LucideIcon;
  title: string;
  hint?: string;
  tone?: keyof typeof TONES;
  badge?: React.ReactNode;
  action?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-xl border border-zinc-200 bg-white">
      <div className="flex items-start gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-start gap-3 text-left cursor-pointer"
        >
          <span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-md", TONES[tone])}>
            <Icon className="h-3.5 w-3.5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="text-sm font-semibold text-zinc-900">{title}</span>
              {badge}
            </span>
            {hint && <span className="mt-0.5 block text-xs text-zinc-500">{hint}</span>}
          </span>
          <ChevronDown className={cn("mt-0.5 h-4 w-4 shrink-0 text-zinc-400 transition-transform", open && "rotate-180")} />
        </button>
        {action}
      </div>
      {open && <div className="space-y-3 border-t border-zinc-100 p-3 sm:p-4">{children}</div>}
    </section>
  );
}

export function Badge({ tone = "zinc", children }: { tone?: keyof typeof TONES; children: React.ReactNode }) {
  return <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", TONES[tone])}>{children}</span>;
}

/** Why the AI chose something — shown next to the thing it chose. */
export function AiNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex gap-2 rounded-lg bg-indigo-50 p-2.5 text-xs leading-relaxed text-indigo-900">
      <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

/** The step rail: where you are, what you've looked at, jump anywhere once there's a draft. */
export function Stepper({
  current,
  visited,
  canJump,
  onGo,
}: {
  current: WizardStepId;
  visited: WizardStepId[];
  canJump: boolean;
  onGo: (id: WizardStepId) => void;
}) {
  return (
    <nav aria-label="Setup steps" className="border-b border-zinc-200 bg-white">
      <ol className="flex gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none] sm:px-4">
        {WIZARD_STEPS.map((s, i) => {
          // A tick means "you've looked at this", not "it's before where you are" — Review can be jumped to.
          const on = s.id === current;
          const seen = visited.includes(s.id) && !on;
          const disabled = !on && s.id !== "describe" && !canJump;
          return (
            <li key={s.id} className="shrink-0">
              <button
                type="button"
                disabled={disabled}
                aria-current={on ? "step" : undefined}
                onClick={() => onGo(s.id)}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-40",
                  on ? "bg-indigo-50 text-indigo-700" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900",
                )}
              >
                <span
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold",
                    on ? "bg-indigo-600 text-white" : seen ? "bg-emerald-100 text-emerald-700" : "bg-zinc-100 text-zinc-500",
                  )}
                >
                  {seen ? <Check className="h-3 w-3" /> : i + 1}
                </span>
                {/* Phones keep the rail to one line: only the current step is spelled out. */}
                <span className={cn(!on && "hidden sm:inline")}>{s.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export interface ServerInfo {
  serverId: string;
  name: string;
  connected: boolean;
  tools: { name: string; description: string; risk: Risk }[];
  loading: boolean;
  missing: boolean;
}

/** Each server's name, connection and full tool list (shared cache with the editor's tool panel). */
export function useServers(token: string, serverIds: string[], meta: Record<string, ToolCandidate>): Record<string, ServerInfo> {
  const results = useQueries({
    queries: serverIds.map((id) => ({
      queryKey: ["builder-server-tools", id],
      queryFn: () => builderApi.serverTools(token, id),
      enabled: !!token && id !== "unknown",
      staleTime: 30_000,
    })),
  });
  const out: Record<string, ServerInfo> = {};
  serverIds.forEach((id, i) => {
    const r = results[i];
    const known = Object.values(meta).find((m) => m.server_id === id);
    out[id] = {
      serverId: id,
      name: r?.data?.server_name ?? known?.server_name ?? "Server",
      connected: r?.data?.connected ?? known?.connected ?? false,
      tools: (r?.data?.tools ?? []).map((t) => ({ name: t.name, description: t.description, risk: t.risk.risk })),
      loading: !!r?.isLoading,
      missing: !!r?.isError,
    };
  });
  return out;
}
