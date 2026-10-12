"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Bot, CheckCircle2, ExternalLink, Eye, Plus, Settings2, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Playground } from "@/components/builder/playground";
import { SplitPane } from "@/components/builder/split-pane";
import { ConnectServerDialog } from "@/components/connections/server-connect";
import { AbilitiesStep } from "@/components/builder/agent-wizard/step-abilities";
import { BehaviourStep } from "@/components/builder/agent-wizard/step-behaviour";
import { DescribeStep } from "@/components/builder/agent-wizard/step-describe";
import { EngineStep } from "@/components/builder/agent-wizard/step-engine";
import { IdentityStep } from "@/components/builder/agent-wizard/step-identity";
import { ReviewStep } from "@/components/builder/agent-wizard/step-review";
import { WizardPreview } from "@/components/builder/agent-wizard/wizard-preview";
import { Stepper, useServers, type StepProps } from "@/components/builder/agent-wizard/wizard-ui";
import { ApiError, knowledgeApi } from "@/lib/api";
import { WIZARD_STEPS, blankAgent, groupByServer, matchingProfile, reviewIssues, stepIndex } from "@/lib/builder/agent-wizard";
import { builderApi } from "@/lib/builder/api";
import { emptyRunView, type RunView } from "@/lib/builder/run-state";
import type { DraftAgent, Problem, ToolCandidate } from "@/lib/builder/types";
import type { BuildTarget } from "@/lib/builder/use-builder-actions";
import { useAgentWizard } from "@/stores/agent-wizard-store";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

/** Whether the viewport is at least ``px`` wide (Tailwind's ``lg`` = 1024), kept current on resize. */
function useMinWidth(px: number): boolean {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${px}px)`);
    const sync = () => setOk(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, [px]);
  return ok;
}

/** Renders the guided agent setup over the page while one is in progress. */
export function AgentWizardHost({ onOpen }: { onOpen: (target: BuildTarget) => void }) {
  const open = useAgentWizard((s) => s.open);
  const session = useAgentWizard((s) => s.session);
  // The store is restored from sessionStorage on the client only; render after mount so server and client agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted || !open) return null;
  return <AgentWizard key={session} onOpen={onOpen} />;
}

/**
 * Guided agent creation, in six steps: a description is drafted into a whole
 * agent (identity, tools with reasons, settings, guardrails), each part is
 * shown in its own category with why it's there, and the canvas on the left
 * draws the agent as it's set up. Nothing is saved until Create; then it can
 * be tried right here before opening the full editor.
 *
 * Wide screens split canvas | panel (resizable). Below ``lg`` one shows at a
 * time, with a Setup / Preview switch in the header.
 */
function AgentWizard({ onOpen }: { onOpen: (target: BuildTarget) => void }) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const w = useAgentWizard();
  const [view, setView] = useState<"setup" | "preview">("setup");
  const [connecting, setConnecting] = useState<string | null>(null);
  const [runView, setRunView] = useState<RunView>(emptyRunView);
  const [createError, setCreateError] = useState<string[]>([]);
  const panel = useRef<HTMLDivElement>(null);
  const wide = useMinWidth(1024);

  const profiles = useQuery({ queryKey: ["builder-agent-profiles"], queryFn: () => builderApi.agentProfiles(token), enabled: !!token, staleTime: Infinity });
  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token });
  const kbNames = useMemo(() => Object.fromEntries((kbs.data ?? []).map((k) => [k.id, k.name])), [kbs.data]);

  const draft = w.draft;
  const serverIds = useMemo(() => groupByServer(draft?.config.tool_ids ?? []).map((g) => g.serverId), [draft?.config.tool_ids]);
  const servers = useServers(token, serverIds, w.toolMeta);

  const update = useCallback((next: DraftAgent) => useAgentWizard.getState().setDraft(next), []);
  const addMeta = useCallback((tools: ToolCandidate[]) => {
    const meta = { ...useAgentWizard.getState().toolMeta };
    for (const t of tools) meta[t.tool_id] = { ...meta[t.tool_id], ...t };
    useAgentWizard.getState().set({ toolMeta: meta });
  }, []);

  // Guardrails are suggested from the finished draft (they depend on its
  // tools), in the background, so Behaviour is filled in by the time it's opened.
  const suggestGuardrails = useMutation({
    mutationFn: (d: DraftAgent) =>
      builderApi.suggestGuardrails(token, {
        name: d.name, role: d.role, goal: d.goal, instructions: d.instructions ?? "",
        tool_ids: d.config.tool_ids ?? [], has_knowledge: (d.config.knowledge_base_ids ?? []).length > 0,
      }),
    onSuccess: (res) => {
      const current = useAgentWizard.getState().draft;
      if (!current) return;
      update({ ...current, config: { ...current.config, guardrails: { ...(current.config.guardrails ?? {}), ...res.guardrails } } });
      useAgentWizard.getState().set({ guardrailReason: res.reasoning || null });
    },
  });

  const generate = useMutation({
    mutationFn: (description: string) => builderApi.draftAgent(token, description),
    onSuccess: (res) => {
      const next: DraftAgent = { name: res.name, role: res.role, goal: res.goal, instructions: res.instructions, llm_provider: "", llm_model: "", config: res.config };
      const tools = [...(res.tools.agent ?? []), ...(res.insights?.related_tools ?? [])];
      const meta = Object.fromEntries(tools.map((t) => [t.tool_id, t]));
      useAgentWizard.getState().set({ draft: next, insights: res.insights ?? null, toolMeta: meta, guardrailReason: null, createdId: null });
      useAgentWizard.getState().goTo("identity");
      suggestGuardrails.mutate(next);
    },
  });

  // Read the flag from the store, not this render: StrictMode runs mount
  // effects twice, and the second run must see it already cleared (else the
  // agent is drafted — and paid for — twice).
  useEffect(() => {
    const s = useAgentWizard.getState();
    if (s.autoGenerate) {
      s.set({ autoGenerate: false });
      generate.mutate(s.description);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // "Set it up by hand": an empty agent on the balanced profile.
  useEffect(() => {
    if (draft || w.step === "describe" || (profiles.isLoading && !!token)) return;
    update(blankAgent(profiles.data?.find((p) => p.id === "balanced")));
  }, [draft, w.step, profiles.isLoading, profiles.data, token, update]);

  // Each step starts at its top.
  useEffect(() => {
    panel.current?.scrollTo({ top: 0 });
  }, [w.step]);

  const issues = useMemo(() => {
    if (!draft) return [];
    const disconnected = Object.values(servers).filter((s) => !s.connected && !s.loading && !s.missing).map((s) => ({ serverId: s.serverId, name: s.name }));
    return reviewIssues(draft, { disconnected, knowledgeRecommended: !!w.insights?.knowledge.recommended, needs: w.insights?.needs ?? "" });
  }, [draft, servers, w.insights]);
  const blocked = issues.some((i) => i.level === "block");

  const create = useMutation({
    mutationFn: () => {
      setCreateError([]);
      const d = draft!;
      return builderApi.createAgent(token, {
        name: d.name.trim(), role: d.role.trim(), goal: d.goal.trim(), instructions: (d.instructions ?? "").trim(),
        llm_provider: d.llm_provider ?? "", llm_model: d.llm_model ?? "", config: d.config,
      });
    },
    onSuccess: (agent) => {
      useAgentWizard.getState().set({ createdId: agent.id });
      void queryClient.invalidateQueries({ queryKey: ["builder-agents"] });
    },
    onError: (err) => {
      const problems = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      const detail = err instanceof ApiError && Array.isArray((err.body as { detail?: unknown })?.detail)
        ? ((err.body as { detail: { loc: string[]; msg: string }[] }).detail).map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`)
        : [];
      setCreateError(problems.length || detail.length ? [...problems.map((p) => p.message), ...detail] : [err instanceof Error ? err.message : "Something went wrong."]);
    },
  });

  const close = () => {
    const s = useAgentWizard.getState();
    if (s.createdId) {
      const id = s.createdId;
      s.close();
      onOpen({ kind: "agent", id });
      return;
    }
    if (s.draft && !window.confirm("Discard this agent? Nothing has been saved yet.")) return;
    s.close();
  };

  const at = stepIndex(w.step);
  const meta = WIZARD_STEPS[at];
  const profileLabel = draft && profiles.data ? matchingProfile(draft.config, profiles.data)?.label ?? "Custom" : null;
  const goNext = () => useAgentWizard.getState().goTo(WIZARD_STEPS[Math.min(at + 1, WIZARD_STEPS.length - 1)].id);
  const goBack = () => useAgentWizard.getState().goTo(WIZARD_STEPS[Math.max(at - 1, 0)].id);

  const stepProps: StepProps | null = draft
    ? {
        token, draft, update, insights: w.insights, toolMeta: w.toolMeta, addMeta, servers,
        profiles: profiles.data ?? [], goTo: (s) => useAgentWizard.getState().goTo(s), connect: setConnecting,
      }
    : null;

  const generateError = generate.isError ? (generate.error instanceof Error ? generate.error.message : "Couldn't design the agent.") : null;

  return (
    <div className="builder-dark fixed inset-0 z-40 flex flex-col bg-zinc-950" role="dialog" aria-modal="true" aria-label="Create an agent">
      <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        <Sparkles className="h-4 w-4 shrink-0 text-indigo-600" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-zinc-900">{w.createdId ? "Agent created" : "New agent"}{draft?.name ? ` · ${draft.name}` : ""}</p>
          <p className="hidden truncate text-[11px] text-zinc-500 sm:block">{w.createdId ? "Try it, then open it in the editor." : "Nothing is saved until you create it."}</p>
        </div>
        {/* Narrow screens show one side at a time. */}
        <div className="inline-flex shrink-0 rounded-lg border border-zinc-200 p-0.5 lg:hidden" role="tablist" aria-label="Show">
          {([["setup", "Setup", Settings2], ["preview", "Preview", Eye]] as const).map(([id, label, Icon]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={view === id}
              aria-label={label}
              onClick={() => setView(id)}
              className={cn("inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium cursor-pointer", view === id ? "bg-indigo-600 text-white" : "text-zinc-500")}
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="hidden min-[400px]:inline">{label}</span>
            </button>
          ))}
        </div>
        <button type="button" onClick={close} aria-label={w.createdId ? "Done" : "Close"} className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="min-h-0 flex-1">
        <SplitPane
          open
          storageKey="builder.agent-wizard.split"
          label="Resize the setup panel"
          min={38}
          max={70}
          narrowShows={view === "preview" ? "left" : "right"}
          left={
            <WizardPreview
              draft={draft}
              generating={generate.isPending}
              servers={servers}
              toolMeta={w.toolMeta}
              kbNames={kbNames}
              profileLabel={profileLabel}
              runView={runView}
              visible={view === "preview" || wide}
              vertical={!wide}
              token={token}
              onOpen={(what) => {
                if (!draft) return;
                useAgentWizard.getState().goTo(what === "agent" ? "identity" : "abilities");
                if (!wide) setView("setup");
              }}
            />
          }
          right={
            w.createdId ? (
              <div className="flex h-full flex-col">
                <div className="space-y-3 border-b border-zinc-200 p-4">
                  <p className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
                    <CheckCircle2 className="h-4 w-4" /> {draft?.name || "Your agent"} is ready
                  </p>
                  <p className="text-xs text-zinc-500">Try it below — the canvas shows each tool as it&apos;s used. Everything can still be changed in the editor.</p>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Button size="sm" onClick={close}>
                      <ExternalLink /> Open in editor
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => useAgentWizard.getState().start({})}>
                      <Plus /> Create another
                    </Button>
                  </div>
                </div>
                <div className="min-h-0 flex-1">
                  <Playground
                    kind="agent"
                    targetId={w.createdId}
                    token={token}
                    initialInput={w.insights?.try_asking ?? ""}
                    onView={setRunView}
                    stepName={() => draft?.name || "Agent"}
                  />
                </div>
              </div>
            ) : (
              <div className="flex h-full flex-col">
                <Stepper current={w.step} visited={w.visited} canJump={!!draft} onGo={(s) => useAgentWizard.getState().goTo(s)} />
                <div ref={panel} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                  <div className="mx-auto max-w-2xl space-y-4 p-3 sm:p-5">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-600">Step {at + 1} of {WIZARD_STEPS.length}</p>
                      <h2 className="mt-0.5 text-lg font-semibold text-zinc-900">{meta.title}</h2>
                      <p className="mt-1 text-xs leading-relaxed text-zinc-500">{meta.hint}</p>
                    </div>
                    {w.step === "describe" && (
                      <DescribeStep
                        description={w.description}
                        onChange={(description) => useAgentWizard.getState().set({ description })}
                        generating={generate.isPending}
                        error={generateError}
                        hasDraft={!!draft}
                        onGenerate={() => {
                          if (draft && !window.confirm("Design it again? This replaces what you've set up so far.")) return;
                          generate.mutate(w.description.trim());
                        }}
                        onBlank={() => useAgentWizard.getState().goTo("identity")}
                      />
                    )}
                    {w.step !== "describe" && !stepProps && (
                      <div className="flex justify-center py-10"><Spinner className="h-5 w-5 text-zinc-400" /></div>
                    )}
                    {stepProps && w.step === "identity" && <IdentityStep {...stepProps} />}
                    {stepProps && w.step === "abilities" && <AbilitiesStep {...stepProps} />}
                    {stepProps && w.step === "behaviour" && <BehaviourStep {...stepProps} guardrailReason={w.guardrailReason} />}
                    {stepProps && w.step === "engine" && <EngineStep {...stepProps} />}
                    {stepProps && w.step === "review" && <ReviewStep {...stepProps} issues={issues} kbNames={kbNames} createError={createError} />}
                  </div>
                </div>

                {w.step !== "describe" && (
                  <footer className="flex items-center gap-2 border-t border-zinc-200 bg-white px-3 py-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))] sm:px-5">
                    <Button variant="outline" size="sm" onClick={goBack} disabled={create.isPending} aria-label="Back">
                      <ArrowLeft /> <span className="hidden min-[400px]:inline">Back</span>
                    </Button>
                    <span className="flex-1 text-center text-[11px] text-zinc-400">
                      {w.step === "review" && blocked ? "Fix the items in red to create it" : `${at + 1} / ${WIZARD_STEPS.length}`}
                    </span>
                    {w.step !== "review" && draft && (
                      <button
                        type="button"
                        onClick={() => useAgentWizard.getState().goTo("review")}
                        className="hidden text-xs font-medium text-zinc-500 hover:text-zinc-900 sm:inline cursor-pointer"
                      >
                        Skip to review
                      </button>
                    )}
                    {w.step === "review" ? (
                      <Button size="sm" onClick={() => create.mutate()} disabled={!draft || blocked || create.isPending}>
                        {create.isPending ? <Spinner className="h-4 w-4" /> : <Bot />} Create agent
                      </Button>
                    ) : (
                      <Button size="sm" onClick={goNext} disabled={!draft}>
                        Next <ArrowRight />
                      </Button>
                    )}
                  </footer>
                )}
              </div>
            )
          }
        />
      </div>

      {connecting && (
        <ConnectServerDialog serverId={connecting} token={token} onClose={() => setConnecting(null)} onConnected={() => setConnecting(null)} />
      )}
    </div>
  );
}
