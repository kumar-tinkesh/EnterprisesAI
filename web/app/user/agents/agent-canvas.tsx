"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp,
  Bot,
  ChevronDown,
  Layers,
  ListChecks,
  MessageSquare,
  Network,
  Plus,
  Plug,
  Search,
  Sparkles,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";

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
    placeholder: "Describe an AI agent to build (e.g. An inbox assistant that reads Gmail and drafts replies)...",
    hint: "You'll check and adjust it step by step before it's saved.",
  },
  {
    id: "workflow",
    label: "Workflow",
    Icon: Network,
    placeholder: "Describe an automated workflow to build (e.g. Every morning summarise unread emails and post to Slack)...",
    hint: "It's designed, matched to your tools and opened on the canvas.",
  },
];

const CHIP =
  "inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-zinc-300 transition-colors hover:border-white/20 hover:bg-white/[0.08] hover:text-white disabled:opacity-50 cursor-pointer";

/**
 * Modern AI Compiler Start Page:
 * - Sleek, compact AI command bar at the top (with mode toggle & quick actions)
 * - Full-featured workspace dashboard & card library below (no vertical double-scroller)
 */
export default function BuilderHome({
  hasAnyConnectedServer,
  onOpen,
  onOpenWorkspace,
}: {
  hasAnyConnectedServer: boolean;
  onOpen: (target: BuildTarget) => void;
  onOpenWorkspace?: (target: BuildTarget, tab?: "overview" | "chat" | "simulate" | "health") => void;
}) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const builder = useBuilderActions({ open: onOpen });
  const [mode, setMode] = useState<BuildMode>("agent");
  const [text, setText] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(MODE_KEY);
      if (saved === "agent" || saved === "workflow") setMode(saved);
      const params = new URLSearchParams(window.location.search);
      const p = params.get("prompt");
      if (p) {
        setText(p);
        setIsFocused(true);
      }
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

  // Grow box dynamically with input
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    const minH = isFocused || text.length > 0 ? 56 : 40;
    el.style.height = `${Math.min(Math.max(el.scrollHeight, minH), 140)}px`;
  }, [text, isFocused]);

  // Polish the rough description before building from it.
  const improve = useMutation({
    mutationFn: () =>
      builderApi.improveText(
        token,
        "prompt",
        text,
        `A description of a new ${mode} to build in an AI agent builder.`
      ),
    onSuccess: (r) => setText(r.text),
    onError: (err) =>
      builder.setError(err instanceof Error ? err.message : "Couldn't improve it."),
  });

  const pending = builder.createWithAi.isPending;
  const busy = pending || improve.isPending;
  const current = MODES.find((m) => m.id === mode)!;

  const submit = () => {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    builder.createWithAi.mutate({ mode, description: q }, { onSuccess: () => setText("") });
  };

  const isActive = isFocused || text.trim().length > 0;

  const cancel = () => {
    setText("");
    setIsFocused(false);
    box.current?.blur();
  };

  return (
    <div
      className={cn(
        "animate-fade-up mx-auto flex h-full w-full max-w-6xl flex-col px-4 py-6 transition-all duration-300 sm:px-8 sm:py-8",
        isActive ? "bg-ambient-grid items-center justify-center" : "justify-start"
      )}
    >
      {/* Header: Centered in active mode, top-aligned in idle mode */}
      <header
        className={cn(
          "transition-all duration-300",
          isActive
            ? "mb-6 w-full max-w-2xl text-center"
            : "mb-5 flex w-full flex-wrap items-end justify-between gap-4"
        )}
      >
        <div className="min-w-0">
          <h1
            className={cn(
              "font-semibold text-zinc-100 transition-all",
              isActive ? "text-2xl sm:text-3xl" : "text-xl"
            )}
          >
            Agents & Workflows
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Build, manage, and run your AI agents and automated workflows.
          </p>
        </div>
      </header>

      {/* Connectors Banner (only when idle) */}
      {!hasAnyConnectedServer && !isActive && (
        <div className="mb-4 flex w-full flex-wrap items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-zinc-300">
          <Plug className="h-4 w-4 shrink-0 text-amber-400" />
          <p className="min-w-0 flex-1">Connect an app first — agents and workflows work through them.</p>
          <Link
            href="/user/connectors"
            className="shrink-0 font-medium text-amber-300 underline-offset-2 hover:underline"
          >
            Open Connectors
          </Link>
        </div>
      )}

      {/* AI Command Bar: Centered in active mode, at top in idle mode */}
      <section
        className={cn(
          "relative transition-all duration-300",
          isActive ? "w-full max-w-2xl" : "mb-5 w-full"
        )}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className={cn(
            "rounded-2xl border border-[var(--border-strong)] bg-[var(--surface)] p-3.5 shadow-xs transition-all duration-200",
            isActive
              ? "border-[var(--accent-hover)] shadow-[0_0_32px_rgba(99,102,241,0.22)]"
              : "hover:border-white/20"
          )}
        >
          {/* Header row inside command bar: Mode toggle + Quick actions */}
          <div className="flex flex-wrap items-center justify-between gap-2 pb-2">
            <div
              className="inline-flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5"
              role="tablist"
              aria-label="What to build"
            >
              {MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  role="tab"
                  aria-selected={mode === m.id}
                  disabled={pending}
                  onClick={() => pick(m.id)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors cursor-pointer disabled:cursor-not-allowed",
                    mode === m.id
                      ? "bg-white/10 text-white shadow-xs"
                      : "text-zinc-400 hover:text-zinc-200"
                  )}
                >
                  <m.Icon className="h-3.5 w-3.5" /> {m.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-1.5">
              {mode === "agent" ? (
                <>
                  <button
                    type="button"
                    onClick={() => useAgentWizard.getState().start({})}
                    className={CHIP}
                    title="Configure identity, engine, and abilities step by step"
                  >
                    <ListChecks className="h-3.5 w-3.5 text-zinc-400" />
                    <span>Step-by-step setup</span>
                  </button>
                  <ImportAgentButton
                    token={token}
                    onImported={(a) => onOpen({ kind: "agent", id: a.id })}
                    className={cn(CHIP, "font-normal")}
                  />
                </>
              ) : (
                <button
                  type="button"
                  disabled={builder.createBlank.isPending}
                  onClick={() => builder.createBlank.mutate("workflow")}
                  className={CHIP}
                  title="Create an empty canvas workflow"
                >
                  {builder.createBlank.isPending ? (
                    <Spinner className="h-3.5 w-3.5" />
                  ) : (
                    <Plus className="h-3.5 w-3.5 text-zinc-400" />
                  )}
                  <span>Blank workflow</span>
                </button>
              )}
            </div>
          </div>

          {/* Text input */}
          <div className="relative">
            <label htmlFor="compiler-describe" className="sr-only">
              Describe a new {mode}
            </label>
            <textarea
              id="compiler-describe"
              ref={box}
              value={text}
              disabled={busy}
              placeholder={current.placeholder}
              onFocus={() => setIsFocused(true)}
              onBlur={() => {
                if (!text.trim()) setIsFocused(false);
              }}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  cancel();
                } else if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              className="block w-full resize-none bg-transparent px-1 py-0.5 text-sm leading-relaxed text-zinc-100 outline-none placeholder:text-zinc-500 disabled:opacity-60"
            />
          </div>

          {/* Footer actions row */}
          <div className="mt-2 flex items-center justify-between gap-3 border-t border-white/5 pt-2">
            <p className="min-w-0 flex-1 truncate text-xs text-zinc-500">
              {improve.isPending
                ? "Improving description with AI…"
                : pending
                ? mode === "workflow"
                  ? "Designing workflow & matching tools… this takes a few seconds."
                  : "Opening the setup wizard…"
                : current.hint}
            </p>

            <div className="flex shrink-0 items-center gap-2">
              {isActive && (
                <button
                  type="button"
                  onClick={cancel}
                  className="inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-xs text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200 cursor-pointer transition-colors"
                  title="Cancel and return to dashboard (Esc)"
                >
                  <X className="h-3.5 w-3.5" />
                  <span>Cancel</span>
                </button>
              )}

              <button
                type="button"
                onClick={() => improve.mutate()}
                disabled={busy || text.trim().length < 3}
                title="Rewrite description clearly with AI"
                className="inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200 disabled:opacity-40 cursor-pointer disabled:cursor-default transition-colors"
              >
                {improve.isPending ? (
                  <Spinner className="h-3.5 w-3.5" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
                )}
                <span>Improve</span>
              </button>

              <button
                type="submit"
                aria-label={`Create ${mode}`}
                title="Create (Enter)"
                disabled={busy || text.trim().length < 3}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 text-xs font-medium text-white shadow-xs hover:bg-[var(--accent-hover)] disabled:bg-zinc-800 disabled:text-zinc-500 cursor-pointer disabled:cursor-default transition-all"
              >
                {pending ? (
                  <Spinner className="h-3.5 w-3.5" />
                ) : (
                  <>
                    <span>Generate</span>
                    <ArrowUp className="h-3.5 w-3.5" />
                  </>
                )}
              </button>
            </div>
          </div>
        </form>

        {builder.error && (
          <p className="mt-2 text-center text-xs text-red-400">{builder.error}</p>
        )}
      </section>

      {/* Main Workspace Dashboard: Unified Library & Templates (Hidden when active) */}
      {!isActive && (
        <div className="min-h-0 flex-1 overflow-hidden">
          <AgentLibrary onOpen={onOpen} onOpenWorkspace={onOpenWorkspace} />
        </div>
      )}
    </div>
  );
}

const HEALTH_META: Record<string, { label: string; dot: string; text: string }> = {
  needs_attention: { label: "Needs attention", dot: "bg-amber-400", text: "text-amber-300" },
  testing: { label: "In testing", dot: "bg-sky-400", text: "text-sky-300" },
  not_tested: { label: "Not tested", dot: "bg-zinc-500", text: "text-zinc-500" },
  production_ready: { label: "Ready", dot: "bg-emerald-400", text: "text-emerald-400" },
};

/** Unified Dashboard for Agents, Workflows & Templates with modern card grid */
function AgentLibrary({
  onOpen,
  onOpenWorkspace,
}: {
  onOpen: (target: BuildTarget) => void;
  onOpenWorkspace?: (target: BuildTarget, tab?: "overview" | "chat" | "simulate" | "health") => void;
}) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const [tab, setTab] = useState<"all" | "agent" | "workflow" | "templates">("all");
  const [query, setQuery] = useState("");

  const agents = useQuery({
    queryKey: ["builder-agents"],
    queryFn: () => builderApi.listAgents(token),
    enabled: !!token,
  });
  const workflows = useQuery({
    queryKey: ["builder-workflows"],
    queryFn: () => builderApi.listWorkflows(token),
    enabled: !!token,
  });
  const templates = useQuery({
    queryKey: ["builder-templates", token],
    queryFn: () => builderApi.listTemplates(token),
    enabled: !!token,
  });
  const overview = useQuery({
    queryKey: ["builder-overview"],
    queryFn: () => builderApi.overview(token, 7),
    enabled: !!token,
  });

  const statsMap = useMemo(
    () => new Map((overview.data?.items ?? []).map((i) => [`${i.kind}:${i.id}`, i])),
    [overview.data]
  );

  const agentItems = (agents.data ?? []).map((a) => ({
    kind: "agent" as const,
    id: a.id,
    name: a.name,
    sub: a.role || a.goal || "Autonomous Agent",
    updated: a.updated_at,
    stats: statsMap.get(`agent:${a.id}`),
  }));

  const workflowItems = (workflows.data ?? []).map((w) => ({
    kind: "workflow" as const,
    id: w.id,
    name: w.name,
    sub: w.description || `${w.node_count} steps`,
    updated: w.updated_at,
    stats: statsMap.get(`workflow:${w.id}`),
  }));

  const templateList = templates.data ?? [];
  const allItems = [...agentItems, ...workflowItems].sort((a, b) =>
    b.updated.localeCompare(a.updated)
  );

  const filteredByTab =
    tab === "agent" ? agentItems : tab === "workflow" ? workflowItems : allItems;
  const needle = query.trim().toLowerCase();
  const shown = filteredByTab.filter(
    (it) =>
      !needle ||
      it.name.toLowerCase().includes(needle) ||
      it.sub.toLowerCase().includes(needle)
  );

  const shownTemplates = templateList.filter(
    (t) =>
      !needle ||
      t.name.toLowerCase().includes(needle) ||
      t.summary.toLowerCase().includes(needle) ||
      t.description.toLowerCase().includes(needle)
  );

  const isLoading =
    tab === "templates"
      ? templates.isLoading
      : tab === "agent"
        ? agents.isLoading
        : tab === "workflow"
          ? workflows.isLoading
          : agents.isLoading || workflows.isLoading;

  return (
    <section className="space-y-4" aria-labelledby="library-heading">
      {/* Top Filter and Search Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "all"}
            onClick={() => setTab("all")}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
              tab === "all" ? "bg-white/10 text-white shadow-xs" : "text-zinc-400 hover:text-white"
            )}
          >
            All <span className="tabular-nums opacity-70">({allItems.length})</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "agent"}
            onClick={() => setTab("agent")}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
              tab === "agent" ? "bg-white/10 text-white shadow-xs" : "text-zinc-400 hover:text-white"
            )}
          >
            Agents <span className="tabular-nums opacity-70">({agentItems.length})</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "workflow"}
            onClick={() => setTab("workflow")}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
              tab === "workflow" ? "bg-white/10 text-white shadow-xs" : "text-zinc-400 hover:text-white"
            )}
          >
            Workflows <span className="tabular-nums opacity-70">({workflowItems.length})</span>
          </button>
          {templateList.length > 0 && (
            <button
              type="button"
              role="tab"
              aria-selected={tab === "templates"}
              onClick={() => setTab("templates")}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
                tab === "templates" ? "bg-white/10 text-white shadow-xs" : "text-zinc-400 hover:text-white"
              )}
            >
              Templates <span className="tabular-nums opacity-70">({templateList.length})</span>
            </button>
          )}
        </div>

        {/* Search input */}
        <div className="relative min-w-[220px] max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name or description…"
            className="w-full rounded-lg border border-white/10 bg-white/[0.03] py-1.5 pl-8 pr-8 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-indigo-500/50 focus:bg-white/[0.05] focus:outline-none transition-all"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Scrollable Container for Cards & Templates */}
      <div className="max-h-[calc(100dvh-370px)] min-h-[300px] overflow-y-auto pr-1.5 pb-4 pt-1 [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.15)_transparent] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-white/10 hover:[&::-webkit-scrollbar-thumb]:bg-white/20">
        {/* Loading Skeleton */}
        {isLoading ? (
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 lg:grid-cols-3" aria-busy="true">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex flex-col justify-between rounded-xl border border-white/10 bg-[var(--surface)] p-4">
                <div className="space-y-3">
                  <div className="flex items-center gap-2.5">
                    <div className="h-8 w-8 animate-pulse rounded-lg bg-white/[0.06]" />
                    <div className="h-4 w-1/2 animate-pulse rounded bg-white/[0.06]" />
                  </div>
                  <div className="h-3 w-full animate-pulse rounded bg-white/[0.04]" />
                  <div className="h-3 w-2/3 animate-pulse rounded bg-white/[0.04]" />
                </div>
                <div className="mt-4 flex justify-end gap-2 border-t border-white/5 pt-3">
                  <div className="h-7 w-20 animate-pulse rounded-md bg-white/[0.05]" />
                  <div className="h-7 w-16 animate-pulse rounded-md bg-white/[0.05]" />
                </div>
              </div>
            ))}
          </div>
        ) : /* View: Templates Tab */
        tab === "templates" ? (
          shownTemplates.length === 0 ? (
            <p className="rounded-xl border border-dashed border-white/10 px-4 py-12 text-center text-xs text-zinc-400">
              No templates match &ldquo;{query}&rdquo;.
            </p>
          ) : (
            <TemplatesGrid templates={shownTemplates} onOpen={onOpen} token={token} />
          )
        ) : shown.length === 0 ? (
          /* Empty States */
          <div className="rounded-xl border border-dashed border-white/10 p-8 text-center">
            {query ? (
              <div className="space-y-2">
                <p className="text-sm text-zinc-400">
                  No {tab === "all" ? "items" : `${tab}s`} match &ldquo;{query}&rdquo;.
                </p>
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="text-xs font-medium text-indigo-400 hover:underline cursor-pointer"
                >
                  Clear search filter
                </button>
              </div>
            ) : (
              <div className="mx-auto max-w-sm space-y-3">
                <Bot className="mx-auto h-8 w-8 text-zinc-500" />
                <h3 className="text-sm font-medium text-zinc-200">
                  No {tab === "all" ? "agents or workflows" : `${tab}s`} yet
                </h3>
                <p className="text-xs text-zinc-400">
                  Use the AI prompt bar above to generate one instantly, or explore our pre-built templates.
                </p>
                {templateList.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setTab("templates")}
                    className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-indigo-300 hover:bg-white/[0.08] cursor-pointer transition-colors"
                  >
                    <Sparkles className="h-3.5 w-3.5 text-indigo-400" /> Browse ready-made templates
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          /* Modern Cards Grid */
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 lg:grid-cols-3">
            {shown.map((it, idx) => (
              <div
                key={`${it.kind}:${it.id}`}
                style={{ animationDelay: `${Math.min(idx * 35, 240)}ms` }}
                className="card-lift animate-fade-up group flex flex-col justify-between rounded-xl border border-white/10 bg-[var(--surface)] p-4 shadow-xs hover:border-indigo-500/35 hover:bg-[var(--surface-raised)]"
              >
                {/* Card Header & Content */}
                <div className="space-y-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => onOpen({ kind: it.kind, id: it.id })}
                      className="flex min-w-0 flex-1 items-center gap-2.5 text-left cursor-pointer"
                      title={`Open ${it.name} in canvas editor`}
                    >
                      <TypeIcon kind={it.kind} />
                      <span className="truncate text-sm font-medium text-zinc-100 group-hover:text-white transition-colors">
                        {it.name}
                      </span>
                    </button>
                    <span className="shrink-0 text-[11px] text-zinc-500">
                      {timeAgo(it.updated)}
                    </span>
                  </div>

                  <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
                    {it.sub}
                  </p>

                  {it.stats && (
                    <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px]">
                      <span className={cn("inline-flex items-center gap-1 font-medium", HEALTH_META[it.stats.health_status]?.text)}>
                        <span className={cn("h-1.5 w-1.5 rounded-full", HEALTH_META[it.stats.health_status]?.dot)} />
                        {HEALTH_META[it.stats.health_status]?.label}
                      </span>
                      {it.stats.last_run_at && (
                        <span className="text-zinc-500">
                          · {timeAgo(it.stats.last_run_at)}
                        </span>
                      )}
                      {it.stats.runs ? (
                        <span className="text-zinc-500 tabular-nums">
                          · {it.stats.runs} run{it.stats.runs === 1 ? "" : "s"}
                        </span>
                      ) : null}
                    </div>
                  )}
                </div>

                {/* Card Action Footer */}
                <div className="mt-4 flex items-center justify-end gap-2 border-t border-white/5 pt-3">
                  <button
                    type="button"
                    onClick={() =>
                      onOpenWorkspace
                        ? onOpenWorkspace({ kind: it.kind, id: it.id }, "chat")
                        : onOpen({ kind: it.kind, id: it.id })
                    }
                    className="inline-flex h-7 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-2.5 text-xs font-medium text-zinc-200 hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer"
                    title="Open Workspace with this agent/workflow"
                  >
                    <MessageSquare className="h-3 w-3 text-indigo-400" />
                    <span>Playground</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onOpen({ kind: it.kind, id: it.id })}
                    className="inline-flex h-7 items-center gap-1.5 rounded-md border border-indigo-500/30 bg-indigo-500/10 px-2.5 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 hover:text-indigo-200 cursor-pointer transition-colors"
                    title="Edit in visual canvas"
                  >
                    <Layers className="h-3 w-3" />
                    <span>Canvas</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** Grid view for ready-made templates inside the dashboard */
function TemplatesGrid({
  templates,
  onOpen,
  token,
}: {
  templates: any[];
  onOpen: (target: BuildTarget) => void;
  token: string;
}) {
  const queryClient = useQueryClient();
  const workflows = useQuery({
    queryKey: ["builder-workflows"],
    queryFn: () => builderApi.listWorkflows(token),
    enabled: !!token,
  });

  const create = useMutation({
    mutationFn: (key: string) => builderApi.createFromTemplate(token, key),
    onSuccess: (wf) => {
      void queryClient.invalidateQueries({ queryKey: ["builder-workflows"] });
      onOpen({ kind: "workflow", id: wf.id });
    },
  });

  const use = (key: string, name: string) => {
    const existing = (workflows.data ?? [])
      .filter((w) => w.can_manage && w.name === name)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    if (existing) onOpen({ kind: "workflow", id: existing.id });
    else create.mutate(key);
  };

  return (
    <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 lg:grid-cols-3">
      {templates.map((t, idx) => {
        const sum = needsSummary(t.systems);
        const isBusy = create.isPending && create.variables === t.key;
        return (
          <div
            key={t.key}
            style={{ animationDelay: `${Math.min(idx * 35, 240)}ms` }}
            className="card-lift animate-fade-up flex flex-col justify-between rounded-xl border border-white/10 bg-[var(--surface)] p-4 shadow-xs hover:border-indigo-500/35 hover:bg-[var(--surface-raised)]"
          >
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <WorkflowIcon className="h-4 w-4 text-indigo-400" />
                <h4 className="truncate text-sm font-medium text-zinc-100">{t.name}</h4>
              </div>
              <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">{t.summary}</p>
            </div>

            <div className="mt-4 flex items-center justify-between border-t border-white/5 pt-3">
              <span
                className={cn(
                  "text-[11px] font-medium",
                  sum.blocked ? "text-amber-400" : "text-emerald-400"
                )}
              >
                {sum.ready} of {sum.total} app{sum.total === 1 ? "" : "s"} ready
              </span>

              <button
                type="button"
                disabled={create.isPending}
                onClick={() => use(t.key, t.name)}
                className="inline-flex h-7 items-center gap-1.5 rounded-md border border-indigo-500/30 bg-indigo-500/10 px-3 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 hover:text-indigo-200 disabled:opacity-50 cursor-pointer transition-colors"
              >
                {isBusy && <Spinner className="h-3 w-3" />}
                <span>Use Template</span>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Ready-made workflows (GET /builder/templates).
 * Kept exported for external consumers (e.g. Executions page).
 */
export function Templates({
  onOpen,
  title = "Start from a template",
}: {
  onOpen: (target: BuildTarget) => void;
  title?: string;
}) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [shown, setShown] = useState<string | null>(null);
  const templates = useQuery({
    queryKey: ["builder-templates", token],
    queryFn: () => builderApi.listTemplates(token),
    enabled: !!token,
  });
  const workflows = useQuery({
    queryKey: ["builder-workflows"],
    queryFn: () => builderApi.listWorkflows(token),
    enabled: !!token,
  });

  const use = (key: string, name: string) => {
    const existing = (workflows.data ?? [])
      .filter((w) => w.can_manage && w.name === name)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
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
      <h2 id="templates-heading" className="text-base font-semibold text-zinc-900">
        {title}
      </h2>
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
                    className={cn(
                      "mt-1 inline-flex items-center gap-1 text-xs cursor-pointer",
                      sum.blocked ? "text-amber-700" : "text-zinc-500 hover:text-zinc-900"
                    )}
                  >
                    {sum.ready} of {sum.total} app{sum.total === 1 ? "" : "s"} connected{" "}
                    <ChevronDown
                      className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
                    />
                  </button>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={create.isPending}
                  onClick={() => use(t.key, t.name)}
                >
                  {create.isPending && create.variables === t.key ? (
                    <Spinner className="h-4 w-4" />
                  ) : null}{" "}
                  Use
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
      {create.error && (
        <p className="text-sm text-red-600">
          {create.error instanceof Error ? create.error.message : "Couldn't create it."}
        </p>
      )}
    </section>
  );
}
