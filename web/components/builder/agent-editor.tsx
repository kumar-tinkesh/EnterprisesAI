"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type NodeChange } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, ArrowLeft, Bot, Check, ChevronDown, Coins, Download, FlaskConical, Globe, History, Play, Save, Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { AgentConfigPanel, type ConfigTab } from "@/components/builder/agent-wizard/agent-config-panel";
import { BuildBar, barButton, barInput } from "@/components/builder/build-bar";
import { Playground } from "@/components/builder/playground";
import { SplitPane } from "@/components/builder/split-pane";
import { PublishPanel } from "@/components/builder/publish-panel";
import { ExportPanel } from "@/components/builder/export-panel";
import { UsagePanel } from "@/components/builder/usage-panel";
import { TestsPanel } from "@/components/builder/tests-panel";
import { VersionHistory } from "@/components/builder/version-history";
import { nodeTypes, useNodeSizes, type StepNodeType } from "@/components/builder/step-node";
import { toolGraph } from "@/components/builder/tool-graph";
import { ApiError, knowledgeApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { useServers } from "@/components/builder/agent-wizard/wizard-ui";
import { groupByServer } from "@/lib/builder/agent-wizard";
import { emptyRunView, type RunView } from "@/lib/builder/run-state";
import type { DraftAgent, Problem } from "@/lib/builder/types";
import type { BuildTarget } from "@/lib/builder/use-builder-actions";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

type Selected = { kind: "agent"; tab: ConfigTab } | { kind: "history" } | { kind: "tests" } | { kind: "publish" } | { kind: "usage" } | { kind: "export" } | null;
type Notice = { tone: "ok" | "warn" | "error"; text: string; detail?: string[]; reload?: boolean } | null;

const NOTICE_KEY = (id: string) => `builder.agent-notice.${id}`;

/** The agent editor (canvas, settings, schedules, playground) for one saved agent. */
type EditorProps = {
  id: string;
  onBack: () => void;
  onOpen: (target: BuildTarget) => void;
  /** Where the bar's Workflow tab goes (the empty canvas); without it the tab only switches what the bar describes. */
  onExit?: () => void;
};

export function AgentEditor(props: EditorProps) {
  return (
    <ReactFlowProvider>
      <Editor {...props} />
    </ReactFlowProvider>
  );
}

function Editor({ id, onBack, onOpen, onExit }: EditorProps) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const agentQuery = useQuery({ queryKey: ["builder-agent", id], queryFn: () => builderApi.getAgent(token, id), enabled: !!token });
  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token });

  const [form, setForm] = useState<DraftAgent | null>(null);
  const [version, setVersion] = useState(1);
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState<Selected>({ kind: "agent", tab: "identity" });
  const [notice, setNotice] = useState<Notice>(null);
  const [playOpen, setPlayOpen] = useState(false);
  const [runView, setRunView] = useState<RunView>(emptyRunView);
  const [ask, setAsk] = useState("");
  const [request, setRequest] = useState<{ text: string; at: number } | null>(null);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const loaded = useRef(false);
  const flow = useReactFlow();
  const [switchOpen, setSwitchOpen] = useState(false);
  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token && switchOpen });

  useEffect(() => {
    const t = setTimeout(() => flow.fitView({ padding: 0.3, maxZoom: 1, duration: 200 }), 60);
    return () => clearTimeout(t);
  }, [playOpen, flow]);

  useEffect(() => {
    const a = agentQuery.data;
    if (!a || loaded.current) return;
    loaded.current = true;
    setForm({ name: a.name, role: a.role, goal: a.goal, instructions: a.instructions, llm_provider: a.llm_provider, llm_model: a.llm_model, config: a.config });
    setVersion(a.version);
    try {
      const raw = window.sessionStorage.getItem(NOTICE_KEY(id));
      if (raw) {
        setNotice(JSON.parse(raw));
        window.sessionStorage.removeItem(NOTICE_KEY(id));
      }
    } catch {
      /* none */
    }
  }, [agentQuery.data, id]);

  const update = useCallback((next: DraftAgent) => {
    setForm(next);
    setDirty(true);
  }, []);

  const save = useMutation({
    mutationFn: () =>
      builderApi.updateAgent(token, id, {
        name: form!.name,
        role: form!.role,
        goal: form!.goal,
        instructions: form!.instructions ?? "",
        llm_provider: form!.llm_provider ?? "",
        llm_model: form!.llm_model ?? "",
        config: form!.config,
        expected_version: version,
      }),
    onSuccess: (a) => {
      setVersion(a.version);
      setForm({ name: a.name, role: a.role, goal: a.goal, instructions: a.instructions, llm_provider: a.llm_provider, llm_model: a.llm_model, config: a.config });
      setDirty(false);
      setNotice({ tone: "ok", text: "Saved." });
      queryClient.setQueryData(["builder-agent", id], a);
      void queryClient.invalidateQueries({ queryKey: ["builder-versions", "agent", id] });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setNotice({ tone: "error", text: err.message, reload: true });
        return;
      }
      const problems = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      const fieldErrors = err instanceof ApiError && Array.isArray((err.body as { detail?: unknown })?.detail)
        ? ((err.body as { detail: { loc: string[]; msg: string }[] }).detail).map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`)
        : [];
      setNotice({ tone: "error", text: "Not saved.", detail: [...problems.map((p) => p.message), ...fieldErrors] });
    },
  });

  const restore = useMutation({
    mutationFn: (v: number) => builderApi.restoreAgentVersion(token, id, v, version),
    onSuccess: (a, v) => {
      setVersion(a.version);
      setForm({ name: a.name, role: a.role, goal: a.goal, instructions: a.instructions, llm_provider: a.llm_provider, llm_model: a.llm_model, config: a.config });
      setDirty(false);
      setNotice({ tone: "ok", text: `Version ${v} is back (saved as version ${a.version}).` });
      queryClient.setQueryData(["builder-agent", id], a);
      void queryClient.invalidateQueries({ queryKey: ["builder-versions", "agent", id] });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setNotice({ tone: "error", text: err.message, reload: true });
        return;
      }
      const problems = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Couldn't restore that version.", detail: problems.map((p) => p.message) });
    },
  });

  const ensureSaved = useCallback(async () => {
    if (!dirty) return true;
    try {
      await save.mutateAsync();
      return true;
    } catch {
      return false;
    }
  }, [dirty, save]);

  const toolIds = form?.config.tool_ids ?? [];
  const kbIds = form?.config.knowledge_base_ids ?? [];
  const kbName = (kid: string) => kbs.data?.find((k) => k.id === kid)?.name ?? "Knowledge base";
  const active = runView.activeTool["agent"];

  const { sizes, track } = useNodeSizes();
  const serverIds = useMemo(() => groupByServer(toolIds).map((g) => g.serverId), [toolIds]);
  const servers = useServers(token, serverIds, {});
  // agent → connector (connect it there, once) → its tools.
  const tools = useMemo(
    () =>
      toolGraph({
        toolIds,
        server: (sid) => {
          const s = servers[sid];
          return s && !s.missing ? { name: s.loading ? "Connector" : s.name, connected: s.loading ? undefined : s.connected } : undefined;
        },
        toolSubtitle: () => "A tool this agent may call",
        active,
        usedTools: runView.usedTools,
        token,
        agent: positions["agent"] ?? { x: 320, y: Math.max(0, (Math.max(toolIds.length, kbIds.length, 1) - 1) * 55) },
        at: (key, fallback) => positions[key] ?? fallback,
      }),
    [toolIds, kbIds.length, servers, active, runView.usedTools, token, positions],
  );
  const flowNodes: StepNodeType[] = useMemo(() => {
    if (!form) return [];
    const at = (key: string, fallback: { x: number; y: number }) => positions[key] ?? fallback;
    const nodes: StepNodeType[] = [
      {
        id: "agent",
        type: "step",
        position: at("agent", { x: 320, y: Math.max(0, (Math.max(toolIds.length, kbIds.length, 1) - 1) * 55) }),
        selected: selected?.kind === "agent" && selected.tab !== "abilities",
        data: { type: "agent", title: form.name || "Agent", subtitle: form.goal, problems: [], state: runView.steps["agent"], detail: active ? `Calling ${active}…` : null },
      },
    ];
    nodes.push(...tools.nodes.map((n) => ({ ...n, selected: selected?.kind === "agent" && selected.tab === "abilities" })));
    kbIds.forEach((kid, i) => {
      nodes.push({
        id: `kb:${kid}`,
        type: "step",
        position: at(`kb:${kid}`, { x: 0, y: i * 110 }),
        data: { type: "knowledge", title: kbName(kid), subtitle: "Searched when it needs facts", problems: [] },
      });
    });
    return nodes.map((n) => (sizes[n.id] ? { ...n, measured: sizes[n.id] } : n));
  }, [form, toolIds, kbIds, positions, selected, runView, active, sizes, tools]); // eslint-disable-line react-hooks/exhaustive-deps

  const flowEdges: Edge[] = useMemo(
    () => [
      ...tools.edges,
      ...kbIds.map((kid) => ({ id: `k:${kid}`, source: `kb:${kid}`, target: "agent", style: { stroke: "#c4b5fd", strokeDasharray: "4 4" } })),
    ],
    [tools.edges, kbIds],
  );

  const onNodesChange = useCallback((changes: NodeChange<StepNodeType>[]) => {
    track(changes);
    for (const c of changes) {
      if (c.type === "position" && c.position) setPositions((p) => ({ ...p, [c.id]: c.position! }));
      if (c.type === "select" && c.selected) {
        // The agent opens its settings; a tool or a document opens them on Abilities, where those live.
        setSelected({ kind: "agent", tab: c.id === "agent" ? "identity" : "abilities" });
      }
    }
  }, [track]);

  if (agentQuery.isError) {
    return <div className="builder-dark flex h-screen items-center justify-center bg-zinc-950 text-sm text-zinc-500">{agentQuery.error instanceof Error ? agentQuery.error.message : "Couldn't load this agent."}</div>;
  }
  if (!form) {
    return <div className="builder-dark flex h-screen items-center justify-center bg-zinc-950"><Spinner className="h-6 w-6 text-zinc-400" /></div>;
  }
  const readOnly = agentQuery.data ? !agentQuery.data.can_manage : false;

  return (
    <div className="builder-dark flex h-screen flex-col bg-zinc-950">
      <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-2 py-2 sm:px-3">
        <button type="button" onClick={onBack} className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer" aria-label="Back">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="relative shrink-0">
          <button type="button" className="flex h-8 items-center gap-1 rounded-md px-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer" onClick={() => setSwitchOpen((o) => !o)} aria-label="Switch agent" aria-expanded={switchOpen} title="Switch agent">
            <Bot className="h-4 w-4 text-indigo-400" /> <ChevronDown className="h-3.5 w-3.5" />
          </button>
          {switchOpen && (
            <div className="absolute left-0 top-10 z-40 max-h-80 w-72 overflow-y-auto rounded-xl border border-zinc-200 bg-white p-1.5 shadow-lg">
              {agents.isLoading && <div className="flex justify-center p-3"><Spinner className="h-4 w-4 text-zinc-400" /></div>}
              {(agents.data ?? []).map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => {
                    setSwitchOpen(false);
                    if (a.id === id) return;
                    if (dirty && !window.confirm("You have unsaved changes here. Leave anyway?")) return;
                    onOpen({ kind: "agent", id: a.id });
                  }}
                  className={cn("flex w-full flex-col rounded-lg px-2.5 py-2 text-left text-xs hover:bg-zinc-100 cursor-pointer", a.id === id ? "text-indigo-600" : "text-zinc-700")}
                >
                  <span className="w-full truncate font-medium">{a.name}</span>
                  {a.goal && <span className="w-full truncate text-[10px] text-zinc-400">{a.goal}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        <Input aria-label="Agent name" className="h-8 w-full min-w-0 max-w-56 border-transparent font-semibold hover:border-zinc-200" value={form.name} disabled={readOnly} onChange={(e) => update({ ...form, name: e.target.value })} />
        <span className={cn("hidden shrink-0 text-xs md:inline", dirty ? "text-amber-600" : "text-zinc-400")}>{readOnly ? "View only — shared by a teammate" : dirty ? "Unsaved changes" : "Saved"}</span>
        {/* Narrow screens keep the icons; the labels come back from lg. */}
        <div className="ml-auto flex shrink-0 gap-1.5 sm:gap-2">
          <Button
            size="sm"
            variant="outline"
            aria-label="Settings"
            className={cn("h-8 px-2 lg:px-3", selected?.kind === "agent" && "bg-indigo-50")}
            onClick={() => setSelected(selected?.kind === "agent" ? null : { kind: "agent", tab: "identity" })}
          >
            <Settings2 /> <span className="hidden lg:inline">Settings</span>
          </Button>
          {!readOnly && (
            <Button
              size="sm"
              variant="outline"
              aria-label="Publish"
              className={cn("h-8 px-2 lg:px-3", selected?.kind === "publish" && "bg-indigo-50")}
              onClick={() => setSelected(selected?.kind === "publish" ? null : { kind: "publish" })}
            >
              <Globe /> <span className="hidden lg:inline">Publish</span>
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            aria-label="Export"
            className={cn("h-8 px-2 lg:px-3", selected?.kind === "export" && "bg-indigo-50")}
            onClick={() => setSelected(selected?.kind === "export" ? null : { kind: "export" })}
          >
            <Download /> <span className="hidden xl:inline">Export</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            aria-label="Usage and cost"
            className={cn("h-8 px-2 lg:px-3", selected?.kind === "usage" && "bg-indigo-50")}
            onClick={() => setSelected(selected?.kind === "usage" ? null : { kind: "usage" })}
          >
            <Coins /> <span className="hidden xl:inline">Usage</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            aria-label="Tests"
            className={cn("h-8 px-2 lg:px-3", selected?.kind === "tests" && "bg-indigo-50")}
            onClick={() => setSelected(selected?.kind === "tests" ? null : { kind: "tests" })}
          >
            <FlaskConical /> <span className="hidden lg:inline">Tests</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            aria-label="History"
            className={cn("h-8 px-2 lg:px-3", selected?.kind === "history" && "bg-indigo-50")}
            onClick={() => setSelected(selected?.kind === "history" ? null : { kind: "history" })}
          >
            <History /> <span className="hidden lg:inline">History</span>
          </Button>
          <Button size="sm" variant="outline" aria-label="Test" className={cn("h-8 px-2 lg:px-3", playOpen && "bg-indigo-50")} onClick={() => setPlayOpen((o) => !o)}>
            <Play /> <span className="hidden lg:inline">Test</span>
          </Button>
          {!readOnly && (
            <Button size="sm" aria-label="Save" className="h-8 px-2 lg:px-3" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Spinner className="h-4 w-4" /> : <Save />} <span className="hidden sm:inline">Save</span>
            </Button>
          )}
        </div>
      </header>
      {notice && (
        <div className={cn("flex items-start gap-2 border-b px-4 py-2 text-xs", notice.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : notice.tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-800")}>
          {notice.tone === "ok" ? <Check className="mt-0.5 h-3.5 w-3.5" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5" />}
          <div className="flex-1">
            <p className="font-medium">{notice.text}</p>
            {notice.detail?.map((d, i) => <p key={i}>• {d}</p>)}
          </div>
          {notice.reload && <button type="button" className="font-medium underline cursor-pointer" onClick={() => window.location.reload()}>Reload</button>}
          <button type="button" aria-label="Dismiss" className="cursor-pointer" onClick={() => setNotice(null)}>×</button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <SplitPane
          open={playOpen}
          narrowShows="right"
          left={
            <div className="relative h-full">
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onPaneClick={() => setSelected(null)}
                nodesConnectable={false}
                deleteKeyCode={null}
                fitView
                fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
                proOptions={{ hideAttribution: true }}
                colorMode="dark"
              >
                <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#3f3f46" />
                <Controls showInteractive={false} />
              </ReactFlow>
              {selected?.kind === "publish" && (
                <div className="absolute inset-y-0 right-0 z-10 w-full border-l sm:w-96 border-zinc-200 bg-white shadow-lg">
                  <PublishPanel
                    kind="agent"
                    targetId={id}
                    name={form.name}
                    token={token}
                    currentVersion={version}
                    dirty={dirty}
                    onClose={() => setSelected(null)}
                  />
                </div>
              )}
              {selected?.kind === "usage" && (
                <div className="absolute inset-y-0 right-0 z-10 w-full border-l sm:w-96 border-zinc-200 bg-white shadow-lg">
                  <UsagePanel kind="agent" targetId={id} token={token} onClose={() => setSelected(null)} />
                </div>
              )}
              {selected?.kind === "export" && agentQuery.data && (
                <div className="absolute inset-y-0 right-0 z-10 w-full border-l sm:w-96 border-zinc-200 bg-white shadow-lg">
                  <ExportPanel agent={agentQuery.data} token={token} onClose={() => setSelected(null)} />
                </div>
              )}
              {selected?.kind === "tests" && (
                <div className="absolute inset-y-0 right-0 z-10 w-full border-l sm:w-96 border-zinc-200 bg-white shadow-lg">
                  <TestsPanel
                    kind="agent"
                    targetId={id}
                    token={token}
                    canManage={!readOnly}
                    beforeRun={readOnly ? undefined : ensureSaved}
                    onClose={() => setSelected(null)}
                  />
                </div>
              )}
              {selected?.kind === "history" && (
                <div className="absolute inset-y-0 right-0 z-10 w-full border-l sm:w-80 border-zinc-200 bg-white shadow-lg">
                  <VersionHistory
                    kind="agent"
                    targetId={id}
                    token={token}
                    canRestore={!readOnly}
                    dirty={dirty}
                    restoring={restore.isPending}
                    onRestore={(v) => restore.mutate(v)}
                    onClose={() => setSelected(null)}
                  />
                </div>
              )}
              {selected?.kind === "agent" && (
                <div className="absolute inset-y-0 right-0 z-10 w-full border-l border-zinc-200 bg-white shadow-lg sm:w-[30rem]">
                  <AgentConfigPanel
                    agentId={id}
                    value={form}
                    token={token}
                    readOnly={readOnly}
                    onChange={update}
                    tab={selected.tab}
                    onTab={(tab) => setSelected({ kind: "agent", tab })}
                    onClose={() => setSelected(null)}
                  />
                </div>
              )}
            </div>
          }
          right={
            <Playground
              kind="agent"
              targetId={id}
              token={token}
              beforeRun={readOnly ? undefined : ensureSaved}
              onView={setRunView}
              request={request}
              stepName={() => form.name || "Agent"}
              onClose={() => {
                setPlayOpen(false);
                setRunView(emptyRunView);
              }}
            />
          }
        />
      </div>
      <BuildBar
        current="agent"
        onOpen={onOpen}
        onExit={onExit ? () => {
          if (dirty && !window.confirm("You have unsaved changes here. Leave anyway?")) return false;
          onExit();
          return true;
        } : undefined}
        edit={
          <form
            className="flex min-w-0 flex-1 items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const text = ask.trim();
              if (!text) return;
              setPlayOpen(true);
              setRequest({ text, at: Date.now() });
              setAsk("");
            }}
          >
            <input aria-label="Ask this agent" className={barInput} placeholder={`Ask ${form.name || "this agent"} something and press Run`} value={ask} onChange={(e) => setAsk(e.target.value)} />
            <button type="submit" disabled={!ask.trim()} className={cn(barButton, "bg-emerald-600 text-white hover:bg-emerald-500")}>
              <Play className="h-3.5 w-3.5 fill-current" /> Run
            </button>
          </form>
        }
      />
    </div>
  );
}
