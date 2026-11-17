"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Bot, ChevronDown, ListChecks, MessageSquare, Network, Plus, Plug, Search, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import { useBuilderActions } from "@/lib/builder/use-builder-actions";
import { useAuthStore } from "@/stores/auth-store";
import { ImportAgentButton } from "@/components/builder/import-agent";
import { NeedsList, needsSummary } from "@/components/builder/tool-needs";
import { TypeIcon } from "@/components/builder/type-icon";
import { timeAgo } from "@/components/builder/version-history";
import type { BuildMode, BuildTarget } from "@/lib/builder/use-builder-actions";
import { useAgentWizard } from "@/stores/agent-wizard-store";
import { cn } from "@/lib/utils";

const MODE_KEY = "compiler.mode"; // shared with the build bar in the editors
const MODES: { id: BuildMode; label: string; Icon: typeof Bot; placeholder: string; hint: string }[] = [
  {
    id: "agent",
    label: "Agent",
    Icon: Bot,
    placeholder: "e.g. An inbox assistant that reads my Gmail and drafts replies",
    hint: "You'll check and adjust it step by step before it's saved.",
  },
  {
    id: "workflow",
    label: "Workflow",
    Icon: Network,
    placeholder: "e.g. Every morning, summarise my unread Gmail and post it to Slack #team",
    hint: "It's designed, matched to your tools and opened on the canvas.",
  },
];

const CHIP = "inline-flex items-center gap-1.5 rounded-full border border-zinc-200 px-3 py-1.5 text-sm text-zinc-700 transition-colors hover:border-zinc-300 hover:bg-zinc-50 hover:text-zinc-900 disabled:opacity-50 cursor-pointer";

/**
 * The AI Compiler's start: say what to build (an agent or a workflow) in one
 * box, or take another way in — step by step, a file, a blank workflow, a
 * template — or reopen something recent.
 */
export default function BuilderHome({ hasAnyConnectedServer, onOpen }: { hasAnyConnectedServer: boolean; onOpen: (target: BuildTarget) => void }) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const builder = useBuilderActions({ open: onOpen });
  const [mode, setMode] = useState<BuildMode>("agent");
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(MODE_KEY);
      if (saved === "agent" || saved === "workflow") setMode(saved);
    } catch {
      /* default */
    }
  }, []);
  const pick = (m: BuildMode) => {
    setMode(m);
    builder.setError(null);
    try {
      window.localStorage.setItem(MODE_KEY, m);
    } catch {
      /* not remembered */
    }
    box.current?.focus();
  };

  // The box grows with what's typed.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 72), 200)}px`;
  }, [text]);

  // Polish the rough description before building from it.
  const improve = useMutation({
    mutationFn: () => builderApi.improveText(token, "prompt", text, `A description of a new ${mode} to build in an AI agent builder.`),
    onSuccess: (r) => setText(r.text),
    onError: (err) => builder.setError(err instanceof Error ? err.message : "Couldn't improve it."),
  });

  const pending = builder.createWithAi.isPending;
  const busy = pending || improve.isPending;
  const current = MODES.find((m) => m.id === mode)!;
  const submit = () => {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    builder.createWithAi.mutate({ mode, description: q }, { onSuccess: () => setText("") });
  };

  return (
    <div className="mx-auto mt-8 max-w-2xl space-y-10 pb-10 sm:mt-12">
      {!hasAnyConnectedServer && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-zinc-300">
          <Plug className="h-4 w-4 shrink-0 text-amber-400" />
          <p className="min-w-0 flex-1">Connect an app first — agents and workflows work through them.</p>
          <Link href="/user/connectors" className="shrink-0 font-medium text-amber-300 underline-offset-2 hover:underline">
            Open Connectors
          </Link>
        </div>
      )}

      <section className="space-y-4">
        <h2 className="text-center text-2xl font-semibold text-zinc-900">What do you want to build?</h2>

        <div className="flex justify-center">
          <div className="inline-flex rounded-lg border border-zinc-200 p-1" role="tablist" aria-label="What to build">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                role="tab"
                aria-selected={mode === m.id}
                disabled={pending}
                onClick={() => pick(m.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium transition-colors cursor-pointer disabled:cursor-not-allowed",
                  mode === m.id ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:text-zinc-900",
                )}
              >
                <m.Icon className="h-4 w-4" /> {m.label}
              </button>
            ))}
          </div>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="rounded-2xl border border-[var(--border-strong)] bg-[var(--surface)] p-3 transition focus-within:border-[var(--accent-hover)]"
        >
          <label htmlFor="compiler-describe" className="sr-only">Describe a new {mode}</label>
          <textarea
            id="compiler-describe"
            ref={box}
            value={text}
            disabled={busy}
            placeholder={current.placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            className="block w-full resize-none bg-transparent px-1 text-base text-zinc-900 outline-none placeholder:text-zinc-500 disabled:opacity-60"
          />
          <div className="mt-2 flex items-center gap-3">
            <p className="min-w-0 flex-1 text-xs text-zinc-500">
              {improve.isPending
                ? "Improving your description…"
                : pending
                  ? mode === "workflow" ? "Designing the workflow and matching tools… this can take a few seconds." : "Opening the setup…"
                  : current.hint}
            </p>
            <button
              type="button"
              onClick={() => improve.mutate()}
              disabled={busy || text.trim().length < 3}
              title="Rewrite the description more clearly with AI"
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-sm text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-40 cursor-pointer disabled:cursor-default"
            >
              {improve.isPending ? <Spinner className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />} Improve
            </button>
            <button
              type="submit"
              aria-label={`Create ${mode}`}
              title="Create (Enter)"
              disabled={busy || text.trim().length < 3}
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:bg-zinc-200 disabled:text-zinc-500 cursor-pointer disabled:cursor-default"
            >
              {pending ? <Spinner className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
            </button>
          </div>
        </form>
        {builder.error && <p className="text-center text-sm text-red-600">{builder.error}</p>}

        {/* The other ways in, for the kind picked above. */}
        <div className="flex flex-wrap justify-center gap-2">
          {mode === "agent" ? (
            <>
              <button type="button" onClick={() => useAgentWizard.getState().start({})} className={CHIP}>
                <ListChecks className="h-4 w-4" /> Set up step by step
              </button>
              <ImportAgentButton token={token} onImported={(a) => onOpen({ kind: "agent", id: a.id })} className={cn(CHIP, "border-zinc-200 py-1.5 text-sm font-normal")} />
            </>
          ) : (
            <button type="button" disabled={builder.createBlank.isPending} onClick={() => builder.createBlank.mutate("workflow")} className={CHIP}>
              {builder.createBlank.isPending ? <Spinner className="h-4 w-4" /> : <Plus className="h-4 w-4" />} Start a blank workflow
            </button>
          )}
        </div>
      </section>

      {mode === "workflow" && <Templates onOpen={onOpen} />}
      <AgentLibrary onOpen={onOpen} />
    </div>
  );
}

/** All agents and workflows in one place, searchable and filterable with instant chat & edit access. */
function AgentLibrary({ onOpen }: { onOpen: (target: BuildTarget) => void }) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const [tab, setTab] = useState<"all" | "agent" | "workflow">("all");
  const [query, setQuery] = useState("");
  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });

  const agentItems = (agents.data ?? []).map((a) => ({
    kind: "agent" as const,
    id: a.id,
    name: a.name,
    sub: a.role || a.goal || "Agent",
    updated: a.updated_at,
  }));

  const workflowItems = (workflows.data ?? []).map((w) => ({
    kind: "workflow" as const,
    id: w.id,
    name: w.name,
    sub: w.description || `${w.node_count} steps`,
    updated: w.updated_at,
  }));

  const allItems = [...agentItems, ...workflowItems].sort((a, b) => b.updated.localeCompare(a.updated));
  if (!allItems.length && !agents.isLoading && !workflows.isLoading) return null;

  const filteredByTab = tab === "agent" ? agentItems : tab === "workflow" ? workflowItems : allItems;
  const needle = query.trim().toLowerCase();
  const shown = filteredByTab.filter((it) => !needle || it.name.toLowerCase().includes(needle) || it.sub.toLowerCase().includes(needle));

  return (
    <section className="space-y-4" aria-labelledby="library-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="library-heading" className="text-base font-semibold text-zinc-900">
          Your Agents & Workflows <span className="font-normal text-zinc-500">· {allItems.length}</span>
        </h2>
        <div className="inline-flex rounded-lg border border-zinc-200 p-0.5" role="tablist">
          {(["all", "agent", "workflow"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
                tab === t ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:text-zinc-900"
              )}
            >
              {t === "all" ? `All (${allItems.length})` : t === "agent" ? `Agents (${agentItems.length})` : `Workflows (${workflowItems.length})`}
            </button>
          ))}
        </div>
      </div>

      {allItems.length > 3 && (
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name or description…"
            className="w-full rounded-lg border border-zinc-200 bg-transparent py-1.5 pl-8 pr-3 text-xs text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none"
          />
        </div>
      )}

      {shown.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-200 px-4 py-8 text-center text-xs text-zinc-500">
          No matches found for &ldquo;{query}&rdquo;.
        </p>
      ) : (
        <ul className="divide-y divide-white/5 overflow-hidden rounded-lg border border-white/10 bg-[var(--surface)]">
          {shown.map((it) => (
            <li key={`${it.kind}:${it.id}`} className="group flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-white/[0.04]">
              <button
                type="button"
                onClick={() => onOpen({ kind: it.kind, id: it.id })}
                className="flex min-w-0 flex-1 items-center gap-3 text-left cursor-pointer"
                title={`Open ${it.name} in canvas editor`}
              >
                <TypeIcon kind={it.kind} />
                <div className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-zinc-100 group-hover:text-white">
                    {it.name}
                  </span>
                  <span className="block truncate text-xs text-zinc-400 group-hover:text-zinc-300">{it.sub}</span>
                </div>
              </button>

              <div className="flex shrink-0 items-center gap-2">
                <span className="hidden text-xs text-zinc-400 sm:inline">{timeAgo(it.updated)}</span>
                <Link
                  href={`/user/executions?chat=${it.kind}:${encodeURIComponent(it.id)}&tab=chat`}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-2.5 text-xs font-medium text-zinc-300 hover:bg-white/[0.08] hover:text-white transition-colors"
                  title="Open Chat"
                >
                  <MessageSquare className="h-3 w-3" /> Chat
                </Link>
                <button
                  type="button"
                  onClick={() => onOpen({ kind: it.kind, id: it.id })}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md border border-indigo-500/30 bg-indigo-500/10 px-2.5 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 hover:text-indigo-200 cursor-pointer transition-colors"
                  title="Edit in Canvas"
                >
                  Edit Canvas
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Ready-made workflows (GET /builder/templates). Each lists the systems its
 * steps use and where they stand for this person; it can be created before
 * they're connected — its steps pick each system's tools up once it is.
 */
export function Templates({ onOpen, title = "Start from a template" }: { onOpen: (target: BuildTarget) => void; title?: string }) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [shown, setShown] = useState<string | null>(null);
  const templates = useQuery({ queryKey: ["builder-templates", token], queryFn: () => builderApi.listTemplates(token), enabled: !!token });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });
  // Already made from this template: open that one rather than adding another copy.
  const use = (key: string, name: string) => {
    const existing = (workflows.data ?? []).filter((w) => w.can_manage && w.name === name).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    if (existing) onOpen({ kind: "workflow", id: existing.id });
    else create.mutate(key);
  };
  const create = useMutation({
    mutationFn: (key: string) => builderApi.createFromTemplate(token, key),
    onSuccess: (wf) => {
      void queryClient.invalidateQueries({ queryKey: ["builder-workflows"] });
      onOpen({ kind: "workflow", id: wf.id });
    },
  });
  if (!templates.data?.length) return null;

  return (
    <section className="space-y-3" aria-labelledby="templates-heading">
      <h2 id="templates-heading" className="text-base font-semibold text-zinc-900">{title}</h2>
      <ul className="divide-y divide-zinc-100 overflow-hidden rounded-lg border border-zinc-200">
        {templates.data.map((t) => {
          const sum = needsSummary(t.systems);
          const open = shown === t.key;
          return (
            <li key={t.key} className="px-4 py-3">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-zinc-900">{t.name}</p>
                  <p className="mt-0.5 text-xs text-zinc-500">{t.summary}</p>
                  <button
                    type="button"
                    onClick={() => setShown(open ? null : t.key)}
                    aria-expanded={open}
                    className={cn("mt-1 inline-flex items-center gap-1 text-xs cursor-pointer", sum.blocked ? "text-amber-700" : "text-zinc-500 hover:text-zinc-900")}
                  >
                    {sum.ready} of {sum.total} app{sum.total === 1 ? "" : "s"} connected <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
                  </button>
                </div>
                <Button size="sm" variant="outline" disabled={create.isPending} onClick={() => use(t.key, t.name)}>
                  {create.isPending && create.variables === t.key ? <Spinner className="h-4 w-4" /> : null} Use
                </Button>
              </div>
              {open && (
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-zinc-500">{t.description}</p>
                  <NeedsList token={token} statuses={t.systems} light />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {create.error && <p className="text-sm text-red-600">{create.error instanceof Error ? create.error.message : "Couldn't create it."}</p>}
    </section>
  );
}
