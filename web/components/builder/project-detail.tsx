"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Eye,
  FlaskConical,
  Layers,
  Loader2,
  MessageSquare,
  Minus,
  RefreshCw,
  ShieldAlert,
  SlidersHorizontal,
  X,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ChatPanel, type ChatTarget } from "@/components/builder/chat/chat-panel";
import { TestsPanel } from "@/components/builder/tests-panel";
import { AgentConfigPanel, type ConfigTab } from "@/components/builder/agent-wizard/agent-config-panel";
import { useServers } from "@/components/builder/agent-wizard/wizard-ui";
import { ConnectorIcon } from "@/components/connections/connector-icon";
import { ApiError, knowledgeApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { groupByServer } from "@/lib/builder/agent-wizard";
import { NODE_META, stepTitle, toolName } from "@/lib/builder/graph";
import type { Agent, DraftAgent, Health, Problem, Run, RunStatus, Workflow } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

export type DetailTab = "overview" | "chat" | "edit" | "simulate" | "health";

const TABS: { id: DetailTab; label: string; Icon: typeof Eye }[] = [
  { id: "overview", label: "Overview", Icon: Eye },
  { id: "chat", label: "Chat", Icon: MessageSquare },
  { id: "edit", label: "Edit config", Icon: SlidersHorizontal },
  { id: "simulate", label: "Simulate", Icon: FlaskConical },
  { id: "health", label: "Health", Icon: Activity },
];

const HEALTH_STATUS: Record<Health["status"], { label: string; dot: string; text: string }> = {
  production_ready: { label: "Production ready", dot: "bg-emerald-500", text: "text-emerald-700" },
  testing: { label: "Testing", dot: "bg-amber-500", text: "text-amber-700" },
  needs_attention: { label: "Needs attention", dot: "bg-amber-500", text: "text-amber-700" },
  not_tested: { label: "Not tested", dot: "bg-zinc-400", text: "text-zinc-500" },
};

const RUN_STATUS: Record<RunStatus, { label: string; Icon: typeof CheckCircle2; pill: string }> = {
  succeeded: { label: "Succeeded", Icon: CheckCircle2, pill: "bg-emerald-50 text-emerald-700" },
  failed: { label: "Failed", Icon: XCircle, pill: "bg-red-50 text-red-700" },
  running: { label: "Running", Icon: Loader2, pill: "bg-sky-50 text-sky-700" },
  queued: { label: "Queued", Icon: Clock, pill: "bg-zinc-100 text-zinc-600" },
  waiting: { label: "Waiting", Icon: ShieldAlert, pill: "bg-amber-50 text-amber-700" },
  cancelled: { label: "Cancelled", Icon: XCircle, pill: "bg-zinc-100 text-zinc-600" },
};

function ago(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

const ms = (n: number) => (n >= 60000 ? `${Math.round(n / 60000)} min` : n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${n} ms`);
const took = (r: Run) => (r.started_at && r.finished_at ? new Date(r.finished_at).getTime() - new Date(r.started_at).getTime() : null);

/**
 * Everything about one agent or workflow, beside the list on Executions:
 * what it's set to, a chat with it, its settings, its tests and how ready it is.
 */
export function ProjectDetail({
  target,
  token,
  tab,
  onTab,
  onClose,
  onOpenCanvas,
}: {
  target: ChatTarget;
  token: string;
  tab: DetailTab;
  onTab: (tab: DetailTab) => void;
  onClose: () => void;
  /** Open it on the full canvas editor. */
  onOpenCanvas: () => void;
}) {
  const { kind, id } = target;
  const agentQ = useQuery({ queryKey: ["builder-agent", id], queryFn: () => builderApi.getAgent(token, id), enabled: !!token && kind === "agent" });
  const workflowQ = useQuery({ queryKey: ["builder-workflow", id], queryFn: () => builderApi.getWorkflow(token, id), enabled: !!token && kind === "workflow" });
  const healthQ = useQuery({ queryKey: ["builder-health", kind, id], queryFn: () => builderApi.health(token, kind, id), enabled: !!token, staleTime: 15_000 });
  const item = kind === "agent" ? agentQ.data : workflowQ.data;
  const loadError = kind === "agent" ? agentQ.error : workflowQ.error;
  const canManage = !!item?.can_manage;

  // Health moves with what's done on the other tabs: refetch on every visit.
  const queryClient = useQueryClient();
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ["builder-health", kind, id] });
  }, [tab, kind, id, queryClient]);

  const health = healthQ.data;
  // The list beside it already says who this is; these are the only controls up here.
  const controls = (
    <>
      <Button size="sm" variant="outline" className="h-8 shrink-0" onClick={onOpenCanvas} title="Open it on the canvas editor">
        <Layers /> <span className="hidden sm:inline">Canvas</span>
      </Button>
      <button type="button" onClick={onClose} aria-label="Close" className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer">
        <X className="h-4 w-4" />
      </button>
    </>
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 items-center gap-2 border-b border-zinc-200 px-3 sm:px-4">
        <nav className="flex min-w-0 flex-1 gap-1 overflow-x-auto" role="tablist" aria-label={`${item?.name ?? kind} views`}>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => (t.id === "edit" && kind === "workflow" ? onOpenCanvas() : onTab(t.id))}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-3 text-xs font-semibold transition-colors cursor-pointer",
                tab === t.id ? "border-indigo-500 text-indigo-700" : "border-transparent text-zinc-500 hover:text-zinc-900",
              )}
            >
              <t.Icon className="h-3.5 w-3.5" /> {t.label}
              {t.id === "health" && health?.blockers.some((b) => b.severity === "critical") && <span className="h-1.5 w-1.5 rounded-full bg-red-500" aria-label="Has blockers" />}
            </button>
          ))}
        </nav>
        {/* On Chat they sit with New and History instead. */}
        {tab !== "chat" && controls}
      </header>

      <div className="min-h-0 flex-1">
        {loadError ? (
          <p className="m-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{loadError instanceof Error ? loadError.message : "Couldn't load it."}</p>
        ) : !item ? (
          <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-zinc-400" /></div>
        ) : tab === "chat" ? (
          <ChatPanel key={`${kind}:${id}`} target={target} token={token} onClose={onClose} onEdit={onOpenCanvas} embedded actions={controls} />
        ) : tab === "edit" && kind === "agent" ? (
          <EditAgent agent={item as Agent} token={token} readOnly={!canManage} onDone={() => onTab("overview")} />
        ) : tab === "simulate" ? (
          <div className="h-full [&>div]:h-full">
            <TestsPanel kind={kind} targetId={id} token={token} canManage={canManage} onClose={() => onTab("overview")} />
          </div>
        ) : tab === "health" ? (
          <HealthView health={health} loading={healthQ.isLoading} refreshing={healthQ.isFetching} onRefresh={() => void healthQ.refetch()} onTab={onTab} kind={kind} />
        ) : kind === "agent" ? (
          <AgentOverview agent={item as Agent} token={token} onTab={onTab} />
        ) : (
          <WorkflowOverview workflow={item as Workflow} token={token} onOpenCanvas={onOpenCanvas} />
        )}
      </div>
    </div>
  );
}

/** A labelled row of the read-only view. */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-zinc-100 py-3 last:border-0 sm:grid-cols-[150px_1fr] sm:gap-4">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{label}</span>
      <div className="min-w-0 text-[13px] text-zinc-800">{children}</div>
    </div>
  );
}

const None = ({ children = "None" }: { children?: string }) => <span className="text-zinc-500">{children}</span>;

function Section({ title, hint, action, children }: { title: string; hint?: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex items-end justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
          {hint && <p className="text-xs text-zinc-500">{hint}</p>}
        </div>
        {action}
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white px-4">{children}</div>
    </section>
  );
}

function useRecentRuns(token: string, kind: "agent" | "workflow", id: string) {
  return useQuery({
    queryKey: ["builder-runs", kind, id, "detail"],
    queryFn: () => builderApi.listRuns(token, kind === "agent" ? { agent_id: id, limit: 50 } : { workflow_id: id, limit: 50 }),
    enabled: !!token,
    refetchInterval: 20000,
  });
}

/** Runs, success rate, average time and the last run, over its latest runs. */
function RunStats({ runs }: { runs: Run[] }) {
  const finished = runs.filter((r) => r.status === "succeeded" || r.status === "failed");
  const ok = finished.filter((r) => r.status === "succeeded").length;
  const times = finished.map(took).filter((n): n is number => n !== null);
  const cells = [
    { label: "Recent runs", value: String(runs.length) },
    { label: "Succeeded", value: finished.length ? `${Math.round((ok / finished.length) * 100)}%` : "—" },
    { label: "Avg time", value: times.length ? ms(Math.round(times.reduce((a, b) => a + b, 0) / times.length)) : "—" },
    { label: "Last run", value: runs[0] ? ago(runs[0].created_at) : "never" },
  ];
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-zinc-200 bg-zinc-100 sm:grid-cols-4">
      {cells.map((c) => (
        <div key={c.label} className="bg-white px-4 py-3">
          <p className="text-[11px] text-zinc-500">{c.label}</p>
          <p className="mt-0.5 text-lg font-semibold tabular-nums text-zinc-900">{c.value}</p>
        </div>
      ))}
    </div>
  );
}

function RecentRuns({ runs, loading }: { runs: Run[]; loading: boolean }) {
  if (loading) return <div className="flex justify-center py-6"><Spinner className="h-4 w-4 text-zinc-400" /></div>;
  if (!runs.length) return <p className="py-4 text-sm text-zinc-500">No runs yet. Ask it something on the Chat tab.</p>;
  return (
    <ul className="divide-y divide-zinc-100">
      {runs.slice(0, 6).map((r) => {
        const st = RUN_STATUS[r.status] ?? RUN_STATUS.queued;
        const t = took(r);
        return (
          <li key={r.id} className="flex items-center gap-3 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] text-zinc-900">{r.input?.text || "—"}</span>
              {r.status === "failed" && r.error && <span className="block truncate text-[11px] text-red-600">{r.error}</span>}
            </span>
            <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium", st.pill)}>
              <st.Icon className={cn("h-3 w-3", r.status === "running" && "animate-spin")} /> {st.label}
            </span>
            <span className="hidden w-12 shrink-0 text-right text-[11px] tabular-nums text-zinc-500 sm:block">{t !== null ? ms(t) : "—"}</span>
            <span className="w-16 shrink-0 text-right text-[11px] text-zinc-500">{ago(r.created_at)}</span>
            {r.definition_version ? <span className="hidden w-7 shrink-0 text-right text-[10px] text-zinc-500 md:block">v{r.definition_version}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}

function ToolChips({ toolIds, token }: { toolIds: string[]; token: string }) {
  const groups = useMemo(() => groupByServer(toolIds), [toolIds]);
  const servers = useServers(token, groups.map((g) => g.serverId), {});
  if (!toolIds.length) return <None />;
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-zinc-500">{toolIds.length} tool{toolIds.length === 1 ? "" : "s"} from {groups.length} connector{groups.length === 1 ? "" : "s"}</p>
      {groups.map((g) => {
        const s = servers[g.serverId];
        const name = s && !s.loading ? s.name : "Connector";
        const risks = Object.fromEntries((s?.tools ?? []).map((t) => [t.name, t.risk]));
        return (
          <div key={g.serverId} className="flex items-start gap-2">
            <ConnectorIcon name={name} size="sm" />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-800">
                {name}
                {s && !s.loading && !s.missing && !s.connected && <span className="rounded bg-amber-50 px-1 text-[10px] font-medium text-amber-700">not connected</span>}
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {g.toolIds.map((tid) => {
                  const n = toolName(tid);
                  const risk = risks[n];
                  return (
                    <span
                      key={tid}
                      title={risk ? `${risk}: ${risk === "read" ? "only looks things up" : risk === "edit" ? "creates or changes data" : "removes data"}` : undefined}
                      className={cn(
                        "rounded px-1.5 py-0.5 font-mono text-[10px]",
                        risk === "delete" ? "bg-red-50 text-red-700" : risk === "edit" ? "bg-amber-50 text-amber-700" : "bg-zinc-100 text-zinc-600",
                      )}
                    >
                      {n}
                    </span>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function KnowledgeNames({ ids, token }: { ids: string[]; token: string }) {
  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token && ids.length > 0 });
  if (!ids.length) return <None />;
  return (
    <div className="flex flex-wrap gap-1.5">
      {ids.map((k) => {
        const kb = kbs.data?.find((x) => x.id === k);
        return (
          <span key={k} className="rounded-md bg-violet-50 px-2 py-0.5 text-xs text-violet-700">
            {kb?.name ?? "Knowledge base"}
            {kb ? <span className="text-zinc-500"> · {kb.document_count} docs</span> : null}
          </span>
        );
      })}
    </div>
  );
}

function AgentOverview({ agent, token, onTab }: { agent: Agent; token: string; onTab: (t: DetailTab) => void }) {
  const runs = useRecentRuns(token, "agent", agent.id);
  const cfg = agent.config ?? {};
  const g = cfg.guardrails ?? {};
  const guards = [
    g.injection && "Refuses attempts to override its instructions",
    g.tool_injection && "Ignores instructions hidden in tool results",
    g.pii_input && "Hides personal data in what it's sent",
    g.pii_output && "Hides personal data in its answers",
    g.groundedness && `Checks answers against its documents (${g.groundedness_mode ?? "fast"})`,
  ].filter(Boolean) as string[];
  const asks = (["read", "edit", "delete"] as const).filter((r) => cfg.approvals?.[r] ?? r !== "read");
  const r = cfg.response ?? {};
  const answers = [r.tone, r.verbosity && r.verbosity !== "balanced" ? r.verbosity : "auto length", r.language && r.language !== "auto" ? r.language : null, r.citations ? `citations ${r.citations.replace("_", " ")}` : null, ...(r.formats ?? [])]
    .filter(Boolean)
    .join(" · ");
  const llm = cfg.llm ?? {};
  const rel = cfg.reliability ?? {};

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-5">
        <RunStats runs={runs.data ?? []} />

        <Section title="Configuration" hint="Everything this agent is set to, as it runs." action={agent.can_manage ? <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onTab("edit")}>Edit</Button> : undefined}>
          <Row label="Role">{agent.role || <None>Not set</None>}</Row>
          <Row label="Goal">{agent.goal || <None>Not set</None>}</Row>
          <Row label="Instructions">{agent.instructions ? <span className="whitespace-pre-wrap">{agent.instructions}</span> : <None />}</Row>
          <Row label="Model">
            <span className="font-mono text-xs">{agent.llm_provider ? `${agent.llm_provider}/` : ""}{agent.llm_model || "platform default"}</span>
            {[llm.temperature != null && `temperature ${llm.temperature}`, llm.max_output_tokens && `max ${llm.max_output_tokens} tokens`, llm.reasoning_effort && llm.reasoning_effort !== "auto" && `reasoning ${llm.reasoning_effort}`]
              .filter(Boolean)
              .map((x) => <span key={String(x)} className="ml-2 text-xs text-zinc-500">· {x}</span>)}
          </Row>
          <Row label="How it answers">{answers || <None>Default</None>}</Row>
          <Row label="Tools"><ToolChips toolIds={cfg.tool_ids ?? []} token={token} /></Row>
          <Row label="Knowledge"><KnowledgeNames ids={cfg.knowledge_base_ids ?? []} token={token} /></Row>
          <Row label="Asks you before">{asks.length ? asks.map((a) => ({ read: "reading", edit: "changing data", delete: "deleting data" })[a]).join(", ") : <None>Never, tools run on their own</None>}</Row>
          <Row label="Guardrails">
            {guards.length ? <ul className="list-disc space-y-0.5 pl-4">{guards.map((x) => <li key={x}>{x}</li>)}</ul> : <None>Off</None>}
            {(g.custom_rules ?? []).length > 0 && (
              <ul className="mt-2 space-y-1">{(g.custom_rules ?? []).map((rule) => <li key={rule} className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-700">{rule}</li>)}</ul>
            )}
            {(guards.length > 0 || (g.custom_rules ?? []).length > 0) && <p className="mt-1 text-[11px] text-zinc-500">When a check trips: {g.on_violation === "block" ? "block the answer" : "flag it"}</p>}
          </Row>
          <Row label="Tool limits">
            {cfg.tools?.max_calls ?? 8} calls a run · {cfg.tools?.timeout_seconds ?? 30}s each · on failure {cfg.tools?.on_failure ?? "continue"}
          </Row>
          <Row label="Reliability">
            {rel.retries ? `${rel.retries} retr${rel.retries === 1 ? "y" : "ies"}` : "No retries"}
            {rel.fallback_model && <> · falls back to <span className="font-mono text-xs">{rel.fallback_model}</span></>}
          </Row>
          <Row label="Version">
            v{agent.version} <span className="text-xs text-zinc-500">· updated {ago(agent.updated_at)} · created {new Date(agent.created_at).toLocaleDateString()}</span>
          </Row>
        </Section>

        <Section title="Recent runs" hint="Newest first">
          <RecentRuns runs={runs.data ?? []} loading={runs.isLoading} />
        </Section>
      </div>
    </div>
  );
}

function WorkflowOverview({ workflow, token, onOpenCanvas }: { workflow: Workflow; token: string; onOpenCanvas: () => void }) {
  const runs = useRecentRuns(token, "workflow", workflow.id);
  const agents = useMemo(() => Object.fromEntries(workflow.agents.map((a) => [a.id, a])), [workflow.agents]);
  // Steps in the order they run: breadth-first from the trigger.
  const ordered = useMemo(() => {
    const out = new Map<string, number>();
    const start = workflow.nodes.filter((n) => ["input", "manual_trigger", "schedule_trigger"].includes(n.type)).map((n) => n.id);
    let frontier = start;
    let depth = 0;
    while (frontier.length && depth < 100) {
      const next: string[] = [];
      for (const id of frontier) {
        if (out.has(id)) continue;
        out.set(id, depth);
        next.push(...workflow.edges.filter((e) => e.source === id).map((e) => e.target));
      }
      frontier = next;
      depth++;
    }
    return [...workflow.nodes].sort((a, b) => (out.get(a.id) ?? 999) - (out.get(b.id) ?? 999));
  }, [workflow.nodes, workflow.edges]);
  const trigger = workflow.nodes.find((n) => ["input", "manual_trigger", "schedule_trigger"].includes(n.type));
  const toolIds = [
    ...workflow.nodes.flatMap((n) => (n.type === "agent" ? ((n.draft_agent?.config ?? (n.agent_id ? agents[n.agent_id]?.config : undefined))?.tool_ids ?? []) : [])),
    ...workflow.nodes.filter((n) => n.type === "tool" && n.tool_id).map((n) => n.tool_id!),
  ];
  const kbs = [...new Set([...(workflow.config.default_knowledge_base_ids ?? []), ...(workflow.config.own_knowledge_base_id ? [workflow.config.own_knowledge_base_id] : [])])];
  const ov = workflow.config.approval_overrides ?? {};
  const failure = workflow.config.on_node_failure ?? "abort";

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-5">
        <RunStats runs={runs.data ?? []} />

        <Section title="Steps" hint="In the order they run" action={workflow.can_manage ? <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onOpenCanvas}>Edit on canvas</Button> : undefined}>
          {ordered.length === 0 ? (
            <p className="py-4 text-sm text-zinc-500">No steps yet. Open it on the canvas to add some.</p>
          ) : (
            <ol className="divide-y divide-zinc-100">
              {ordered.map((n, i) => {
                const a = n.type === "agent" ? n.draft_agent ?? (n.agent_id ? agents[n.agent_id] : undefined) : undefined;
                return (
                  <li key={n.id} className="flex items-start gap-3 py-2.5">
                    <span className="mt-0.5 w-5 shrink-0 text-right text-[11px] tabular-nums text-zinc-500">{i + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-[13px] font-medium text-zinc-900">
                        {stepTitle(n, agents)}
                        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-normal text-zinc-500">{NODE_META[n.type].title}</span>
                      </span>
                      {a?.goal && <span className="block truncate text-[11px] text-zinc-500">{a.goal}</span>}
                      {n.type === "tool" && n.tool_id && <span className="block font-mono text-[11px] text-zinc-500">{toolName(n.tool_id)}</span>}
                      {n.type === "condition" && <span className="block text-[11px] text-zinc-500">{n.condition_config?.mode === "rule" ? "Chooses by rules" : "The AI chooses the branch"}</span>}
                      {n.type === "join" && <span className="block text-[11px] text-zinc-500">Waits for {n.join_policy?.mode === "any" ? "any branch" : n.join_policy?.mode === "count" ? `${n.join_policy.min_required} branches` : "every branch"}</span>}
                      {n.type === "human_approval" && n.approval_message && <span className="block truncate text-[11px] text-zinc-500">“{n.approval_message}”</span>}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </Section>

        <Section title="Configuration" hint="How it runs">
          <Row label="Description">{workflow.description || <None>Not set</None>}</Row>
          <Row label="Starts with">{trigger ? NODE_META[trigger.type].title : <None>No trigger yet</None>}</Row>
          <Row label="Agents">{workflow.agents.length ? workflow.agents.map((a) => a.name).join(", ") : <None />}</Row>
          <Row label="Tools"><ToolChips toolIds={[...new Set(toolIds)]} token={token} /></Row>
          <Row label="Knowledge"><KnowledgeNames ids={kbs} token={token} /></Row>
          <Row label="Asks you before">
            {(["edit", "delete"] as const).map((r) => `${r === "edit" ? "changing" : "deleting"} data: ${ov[r] === "always" ? "always" : ov[r] === "never" ? "never" : "as each step says"}`).join(" · ")}
          </Row>
          <Row label="If a step fails">
            {failure === "retry" ? `Retry ${workflow.config.node_retry_count ?? 1}×, then ${workflow.config.node_retry_fallback ?? "abort"}` : failure === "skip" ? "Skip it and carry on" : "Stop the run"}
          </Row>
          <Row label="Limits">
            {workflow.config.max_steps ? `${workflow.config.max_steps} steps` : "No step limit"} · {workflow.config.max_run_seconds ? `${workflow.config.max_run_seconds}s a run` : "no time limit"}
          </Row>
          <Row label="Version">
            v{workflow.version} <span className="text-xs text-zinc-500">· updated {ago(workflow.updated_at)} · created {new Date(workflow.created_at).toLocaleDateString()}</span>
          </Row>
        </Section>

        <Section title="Recent runs" hint="Newest first">
          <RecentRuns runs={runs.data ?? []} loading={runs.isLoading} />
        </Section>
      </div>
    </div>
  );
}

/** The agent's whole configuration in its categories, saved over it or as a copy. */
function EditAgent({ agent, token, readOnly, onDone }: { agent: Agent; token: string; readOnly: boolean; onDone: () => void }) {
  const queryClient = useQueryClient();
  const seed = (a: Agent): DraftAgent => ({ name: a.name, role: a.role, goal: a.goal, instructions: a.instructions, llm_provider: a.llm_provider, llm_model: a.llm_model, config: a.config });
  const [form, setForm] = useState<DraftAgent>(() => seed(agent));
  const [version, setVersion] = useState(agent.version);
  const [dirty, setDirty] = useState(false);
  const [section, setSection] = useState<ConfigTab>("identity");
  const [notice, setNotice] = useState<{ ok: boolean; text: string; detail?: string[] } | null>(null);

  const body = () => ({
    name: form.name.trim(), role: form.role.trim(), goal: form.goal.trim(), instructions: form.instructions ?? "",
    llm_provider: form.llm_provider ?? "", llm_model: form.llm_model ?? "", config: form.config,
  });
  const fail = (err: unknown) => {
    const problems = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
    setNotice({ ok: false, text: err instanceof ApiError && err.status === 409 ? "Someone else saved it meanwhile. Reload to see their version." : "Not saved.", detail: problems.map((p) => p.message) });
  };
  const refresh = (a: Agent) => {
    queryClient.setQueryData(["builder-agent", a.id], a);
    for (const key of [["builder-agents"], ["builder-health", "agent", a.id], ["builder-versions", "agent", a.id], ["builder-chat-target", "agent", a.id]]) void queryClient.invalidateQueries({ queryKey: key });
  };
  const update = useMutation({
    mutationFn: () => builderApi.updateAgent(token, agent.id, { ...body(), expected_version: version }),
    onSuccess: (a) => {
      setVersion(a.version);
      setForm(seed(a));
      setDirty(false);
      setNotice({ ok: true, text: `Saved as v${a.version}.` });
      refresh(a);
    },
    onError: fail,
  });
  const copy = useMutation({
    mutationFn: () => builderApi.createAgent(token, { ...body(), name: `${form.name.trim()} (copy)` }),
    onSuccess: (a) => {
      setNotice({ ok: true, text: `Saved a copy: "${a.name}". This one is unchanged.` });
      void queryClient.invalidateQueries({ queryKey: ["builder-agents"] });
    },
    onError: fail,
  });
  const busy = update.isPending || copy.isPending;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-zinc-100 bg-zinc-50 px-4 py-2.5 sm:px-5">
        <p className="min-w-0 flex-1 text-xs text-zinc-500">
          {readOnly ? "View only: a teammate shared it." : dirty ? <span className="font-medium text-amber-700">Unsaved changes</span> : "Change anything below, then update it, or keep it and save a copy."}
        </p>
        {!readOnly && (
          <>
            <Button size="sm" variant="outline" className="h-8" disabled={busy || !form.name.trim()} onClick={() => copy.mutate()} title="Leave this agent as it is and save these settings as a new one">
              {copy.isPending ? <Spinner className="h-4 w-4" /> : <Copy />} Save as new
            </Button>
            <Button size="sm" className="h-8" disabled={busy || !dirty} onClick={() => update.mutate()}>
              {update.isPending ? <Spinner className="h-4 w-4" /> : <Check />} Update this agent
            </Button>
          </>
        )}
      </div>
      {notice && (
        <div className={cn("flex shrink-0 items-start gap-2 border-b px-4 py-2 text-xs sm:px-5", notice.ok ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800")}>
          {notice.ok ? <Check className="mt-0.5 h-3.5 w-3.5" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5" />}
          <div className="flex-1">
            <p className="font-medium">{notice.text}</p>
            {notice.detail?.map((d) => <p key={d}>• {d}</p>)}
          </div>
          <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)} className="cursor-pointer">×</button>
        </div>
      )}
      <div className="min-h-0 flex-1">
        <AgentConfigPanel
          agentId={agent.id}
          value={form}
          token={token}
          readOnly={readOnly}
          onChange={(next) => {
            setForm(next);
            setDirty(true);
          }}
          tab={section}
          onTab={setSection}
          onClose={() => (!dirty || window.confirm("Leave without saving these changes?")) && onDone()}
        />
      </div>
    </div>
  );
}

/** The score as a ring: a share of a whole. */
function Ring({ score }: { score: number | null }) {
  const size = 84;
  const r = size / 2 - 6;
  const c = 2 * Math.PI * r;
  const color = score == null ? "#3f3f46" : score >= 70 ? "#0ca30c" : score >= 50 ? "#d97706" : "#d03b3b";
  return (
    <span className="relative flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" className="text-zinc-100" strokeWidth="6" />
        {score != null && (
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} className="transition-[stroke-dashoffset] duration-700" />
        )}
      </svg>
      <span className="absolute text-center">
        <span className="block text-xl font-semibold leading-none tabular-nums text-zinc-900">{score ?? "—"}</span>
        {score != null && <span className="block text-[10px] text-zinc-500">/ 100</span>}
      </span>
    </span>
  );
}

const FIX_TAB: Record<string, DetailTab> = { writes_without_injection_guard: "edit", delete_without_approval: "edit", low_test_score: "simulate", high_failure_rate: "overview" };

function HealthView({
  health,
  loading,
  refreshing,
  onRefresh,
  onTab,
  kind,
}: {
  health: Health | undefined;
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onTab: (t: DetailTab) => void;
  kind: "agent" | "workflow";
}) {
  if (loading || !health) return <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-zinc-400" /></div>;
  const st = HEALTH_STATUS[health.status];
  const critical = health.blockers.filter((b) => b.severity === "critical");
  const warnings = health.blockers.filter((b) => b.severity === "warning");

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-5 rounded-xl border border-zinc-200 bg-white p-4 sm:p-5">
          <Ring score={health.score} />
          <div className="min-w-0 flex-1">
            <p className={cn("flex items-center gap-2 text-base font-semibold", st.text)}>
              <span className={cn("h-2 w-2 rounded-full", st.dot)} /> {st.label}
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              {health.status === "not_tested"
                ? `It hasn't run yet. The score so far is from its settings only.`
                : health.status === "production_ready"
                  ? "Ready to put in front of people: it scores well, has a run history, and passed its tests."
                  : health.status === "needs_attention"
                    ? `${critical.length} thing${critical.length === 1 ? "" : "s"} below would embarrass it in front of a real user.`
                    : "Getting there. Run it more and test it to turn the unmeasured parts into evidence."}
            </p>
            <p className="mt-1 text-[11px] text-zinc-500">
              Based on {health.runs_counted} finished run{health.runs_counted === 1 ? "" : "s"}. Parts not measured yet don&apos;t count against it.
            </p>
          </div>
          <Button size="sm" variant="outline" className="h-8" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw className={cn(refreshing && "animate-spin")} /> Recheck
          </Button>
        </div>

        {(critical.length > 0 || warnings.length > 0) && (
          <section className="space-y-2">
            <h3 className="text-sm font-semibold text-zinc-900">What to fix</h3>
            {[...critical, ...warnings].map((b) => {
              const target = FIX_TAB[b.key] ?? (b.key === "not_connected" ? null : kind === "agent" ? "edit" : null);
              return (
                <div key={b.key} className={cn("rounded-xl border p-3.5", b.severity === "critical" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50")}>
                  <p className={cn("flex items-center gap-2 text-sm font-semibold", b.severity === "critical" ? "text-red-700" : "text-amber-700")}>
                    {b.severity === "critical" ? <XCircle className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />} {b.title}
                  </p>
                  <p className="mt-1 text-xs text-zinc-700">{b.detail}</p>
                  <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-zinc-600">
                    <span className="font-medium">Fix:</span> {b.fix}
                    {b.key === "not_connected" && <a href="/user/connectors" className="font-medium text-indigo-600 hover:text-indigo-800">Open Connectors →</a>}
                    {target && target !== "overview" && (
                      <button type="button" onClick={() => onTab(target)} className="font-medium text-indigo-600 hover:text-indigo-800 cursor-pointer">
                        {target === "edit" ? "Open its settings →" : "Open Simulate →"}
                      </button>
                    )}
                  </p>
                </div>
              );
            })}
          </section>
        )}

        <section>
          <h3 className="mb-2 text-sm font-semibold text-zinc-900">What the score is made of</h3>
          <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 bg-white">
            {health.dimensions.map((d) => (
              <Dimension key={d.key} d={d} />
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function Dimension({ d }: { d: Health["dimensions"][number] }) {
  const [open, setOpen] = useState(false);
  const color = d.score == null ? undefined : d.score >= 70 ? "#0ca30c" : d.score >= 50 ? "#d97706" : "#d03b3b";
  return (
    <li className="px-4 py-3">
      <button type="button" onClick={() => d.detail.length && setOpen((o) => !o)} className={cn("flex w-full items-center gap-3 text-left", d.detail.length && "cursor-pointer")} aria-expanded={d.detail.length ? open : undefined}>
        {d.measured ? (
          d.score! >= 70 ? <CheckCircle2 className="h-4 w-4 shrink-0" style={{ color }} /> : <AlertTriangle className="h-4 w-4 shrink-0" style={{ color }} />
        ) : (
          <Minus className="h-4 w-4 shrink-0 text-zinc-400" />
        )}
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-zinc-900">{d.label}</span>
            <span className="text-[10px] text-zinc-500">weight {d.weight}</span>
          </span>
          <span className="block truncate text-xs text-zinc-500">{d.summary}</span>
        </span>
        <span className="hidden w-28 shrink-0 sm:block" aria-hidden>
          <span className="block h-1.5 overflow-hidden rounded-full bg-zinc-100">
            {d.score != null && <span className="block h-full rounded-full" style={{ width: `${d.score}%`, background: color }} />}
          </span>
        </span>
        <span className="w-14 shrink-0 text-right text-xs tabular-nums text-zinc-600">{d.measured ? `${d.score}%` : "not measured"}</span>
      </button>
      {open && d.detail.length > 0 && (
        <ul className="ml-7 mt-2 space-y-0.5 text-[11px] text-zinc-500">
          {d.detail.map((x) => <li key={x}>• {x}</li>)}
        </ul>
      )}
    </li>
  );
}
