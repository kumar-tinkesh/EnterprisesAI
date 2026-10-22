"use client";

import { useState } from "react";
import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, LayoutTemplate, Link2, ListChecks, Network, Plus, Server, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { builderApi } from "@/lib/builder/api";
import { useBuilderActions } from "@/lib/builder/use-builder-actions";
import { useAuthStore } from "@/stores/auth-store";
import { BuildBar } from "@/components/builder/build-bar";
import { ImportAgentButton } from "@/components/builder/import-agent";
import { NeedsList, needsSummary } from "@/components/builder/tool-needs";
import type { BuildMode, BuildTarget } from "@/lib/builder/use-builder-actions";
import { useAgentWizard } from "@/stores/agent-wizard-store";
import { cn } from "@/lib/utils";

/**
 * The AI Compiler's empty canvas: describe an agent or workflow in the bar
 * at the bottom and it opens right here (only the URL changes).
 */
export default function BuilderHome({
  hasAnyConnectedServer,
  onConnections,
  onOpen,
}: {
  hasAnyConnectedServer: boolean;
  onConnections: () => void;
  onOpen: (target: BuildTarget) => void;
}) {
  // The step-by-step setup is for agents; it's hidden while the bar is on Workflow.
  const [mode, setMode] = useState<BuildMode>("agent");
  return (
    <div className="builder-dark flex h-screen flex-col bg-zinc-950">
      <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        <Sparkles className="h-4 w-4 text-indigo-600" />
        <span className="text-sm font-semibold text-zinc-900">AI Compiler</span>
        <span className="hidden text-xs text-zinc-400 sm:inline">Describe an agent or workflow below</span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" className="h-8" onClick={onConnections} aria-label="Connections">
            <Server /> <span className="hidden sm:inline">Connections</span>
          </Button>
        </div>
      </header>

      {!hasAnyConnectedServer && (
        <div className="flex items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          <p className="flex-1">You haven&apos;t connected any MCP server yet — agents and workflows need one to call tools.</p>
          <button type="button" onClick={onConnections} className="inline-flex items-center gap-1 font-medium underline cursor-pointer">
            <Link2 className="h-3 w-3" /> Connect a server
          </button>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <ReactFlowProvider>
          <ReactFlow nodes={[]} edges={[]} colorMode="dark" proOptions={{ hideAttribution: true }}>
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#3f3f46" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </ReactFlowProvider>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
          <div className="flex gap-2 text-indigo-400">
            <Bot className="h-6 w-6" />
            <Network className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium text-zinc-300">What do you want to build?</p>
          <p className="max-w-sm text-xs text-zinc-500">
            Pick Agent or Workflow below and describe it. It&apos;s designed, matched to your tools and opened on this canvas.
          </p>
          {mode === "agent" ? (
            <AgentStart onOpen={onOpen} />
          ) : (
            <WorkflowStart onOpen={onOpen} />
          )}
        </div>
      </div>

      <BuildBar current={null} onOpen={onOpen} onModeChange={setMode} />
    </div>
  );
}

/**
 * Agent mode's own way in: the step-by-step setup, or an agent already made.
 */
function AgentStart({ onOpen }: { onOpen: (target: BuildTarget) => void }) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });
  const recent = [...(agents.data ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  return (
    <div className="pointer-events-auto mt-1 flex w-full max-w-sm flex-col items-center gap-3">
      <div className="flex flex-wrap items-start justify-center gap-2">
        <button
          type="button"
          onClick={() => useAgentWizard.getState().start({})}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-white/5 cursor-pointer"
        >
          <ListChecks className="h-3.5 w-3.5" /> Set up an agent step by step
        </button>
        <ImportAgentButton token={token} onImported={(a) => onOpen({ kind: "agent", id: a.id })} className="border-white/15 text-zinc-200 hover:bg-white/5" />
      </div>
      {recent.length > 0 && (
        <ListPanel title="Open an agent">
          {recent.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => onOpen({ kind: "agent", id: a.id })}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-zinc-200 hover:bg-white/5 cursor-pointer"
            >
              <Bot className="h-3.5 w-3.5 shrink-0 text-indigo-400" />
              <span className="min-w-0 flex-1 truncate">{a.name}</span>
              {a.role && <span className="max-w-[40%] shrink-0 truncate text-xs text-zinc-500">{a.role}</span>}
            </button>
          ))}
        </ListPanel>
      )}
    </div>
  );
}

/** The scrollable list of things already made, under the empty canvas's start button. */
function ListPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="w-full rounded-xl border border-white/10 bg-white/5 p-1.5 text-left">
      <p className="px-2.5 pb-1 pt-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">{title}</p>
      <div className="max-h-56 overflow-y-auto">{children}</div>
    </div>
  );
}

/**
 * Workflow mode's own way in: an empty workflow to wire agents together by
 * hand (Add Step → Agent, then drag the lines), or one already made.
 */
function WorkflowStart({ onOpen }: { onOpen: (target: BuildTarget) => void }) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const { createBlank, error } = useBuilderActions({ open: onOpen });
  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token });
  const recent = [...(workflows.data ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  return (
    <div className="pointer-events-auto mt-1 flex w-full max-w-sm flex-col items-center gap-3">
      <button
        type="button"
        onClick={() => createBlank.mutate("workflow")}
        disabled={createBlank.isPending}
        className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-white/5 disabled:opacity-60 cursor-pointer"
      >
        {createBlank.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />} Start a blank workflow
      </button>
      <p className="text-xs text-zinc-500">Then Add Step → Agent to use the agents you&apos;ve made, and drag lines to run them one after another or side by side.</p>
      {error && <p className="text-xs text-red-400">{error}</p>}
      <TemplatePanel onOpen={onOpen} />
      {recent.length > 0 && (
        <ListPanel title="Open a workflow">
          {recent.map((w) => (
            <button
              key={w.id}
              type="button"
              onClick={() => onOpen({ kind: "workflow", id: w.id })}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-zinc-200 hover:bg-white/5 cursor-pointer"
            >
              <Network className="h-3.5 w-3.5 shrink-0 text-indigo-400" />
              <span className="min-w-0 flex-1 truncate">{w.name}</span>
              <span className="shrink-0 text-xs text-zinc-500">{w.node_count} steps</span>
            </button>
          ))}
        </ListPanel>
      )}
    </div>
  );
}

/**
 * Ready-made workflows (GET /builder/templates). Each lists the systems its
 * steps use and where they stand for this person; it can be created before
 * they're connected — its steps pick each system's tools up once it is.
 */
function TemplatePanel({ onOpen }: { onOpen: (target: BuildTarget) => void }) {
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
    <ListPanel title="Start from a template">
      {templates.data.map((t) => {
        const sum = needsSummary(t.systems);
        return (
          <div key={t.key} className="rounded-lg px-2.5 py-2 hover:bg-white/5">
            <div className="flex items-center gap-2">
              <LayoutTemplate className="h-3.5 w-3.5 shrink-0 text-indigo-400" />
              <span className="min-w-0 flex-1 truncate text-xs font-medium text-zinc-200">{t.name}</span>
              <button
                type="button"
                onClick={() => setShown(shown === t.key ? null : t.key)}
                className={cn("shrink-0 text-xs cursor-pointer", sum.blocked ? "text-amber-400" : "text-emerald-400")}
                aria-expanded={shown === t.key}
              >
                {sum.ready}/{sum.total} systems
              </button>
              <button
                type="button"
                disabled={create.isPending}
                onClick={() => use(t.key, t.name)}
                className="inline-flex shrink-0 items-center gap-1 rounded-md bg-indigo-600 px-2 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-60 cursor-pointer"
              >
                {create.isPending && create.variables === t.key ? <Spinner className="h-3 w-3" /> : <Plus className="h-3 w-3" />} Use
              </button>
            </div>
            <p className="mt-0.5 pl-5 text-xs text-zinc-500">{t.summary}</p>
            {shown === t.key && (
              <div className="mt-1.5 pl-3">
                <p className="mb-1 px-1.5 text-[10.5px] text-zinc-400">{t.description}</p>
                <NeedsList token={token} statuses={t.systems} />
              </div>
            )}
          </div>
        );
      })}
      {create.error && <p className="px-2.5 pb-1 text-xs text-red-400">{create.error instanceof Error ? create.error.message : "Couldn't create it."}</p>}
    </ListPanel>
  );
}
