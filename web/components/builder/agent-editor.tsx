"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, BackgroundVariant, Controls, MarkerType, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type NodeChange } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, ArrowLeft, Check, FlaskConical, Globe, History, Play, Save, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { AgentFields } from "@/components/builder/agent-fields";
import { AgentSchedules } from "@/components/builder/schedule-fields";
import { RiskBadge } from "@/components/builder/fields";
import { Playground } from "@/components/builder/playground";
import { SplitPane } from "@/components/builder/split-pane";
import { PublishPanel } from "@/components/builder/publish-panel";
import { TestsPanel } from "@/components/builder/tests-panel";
import { VersionHistory } from "@/components/builder/version-history";
import { nodeTypes, useNodeSizes, type StepNodeType } from "@/components/builder/step-node";
import { ApiError, knowledgeApi } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { serverIdOf, toolName } from "@/lib/builder/graph";
import { emptyRunView, type RunView } from "@/lib/builder/run-state";
import type { DraftAgent, Problem } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

type Selected = { kind: "agent" } | { kind: "tool"; id: string } | { kind: "history" } | { kind: "tests" } | { kind: "publish" } | null;
type Notice = { tone: "ok" | "warn" | "error"; text: string; detail?: string[]; reload?: boolean } | null;

const NOTICE_KEY = (id: string) => `builder.agent-notice.${id}`;

/** The agent editor (canvas, settings, schedules, playground) for one saved agent. */
export function AgentEditor({ id, onBack }: { id: string; onBack: () => void }) {
  return (
    <ReactFlowProvider>
      <Editor id={id} onBack={onBack} />
    </ReactFlowProvider>
  );
}

function Editor({ id, onBack }: { id: string; onBack: () => void }) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const agentQuery = useQuery({ queryKey: ["builder-agent", id], queryFn: () => builderApi.getAgent(token, id), enabled: !!token });
  const kbs = useQuery({ queryKey: ["knowledge-bases", token], queryFn: () => knowledgeApi.list(token), enabled: !!token });

  const [form, setForm] = useState<DraftAgent | null>(null);
  const [version, setVersion] = useState(1);
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState<Selected>({ kind: "agent" });
  const [notice, setNotice] = useState<Notice>(null);
  const [playOpen, setPlayOpen] = useState(false);
  const [runView, setRunView] = useState<RunView>(emptyRunView);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const loaded = useRef(false);
  const flow = useReactFlow();

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
  const flowNodes: StepNodeType[] = useMemo(() => {
    if (!form) return [];
    const at = (key: string, fallback: { x: number; y: number }) => positions[key] ?? fallback;
    const nodes: StepNodeType[] = [
      {
        id: "agent",
        type: "step",
        position: at("agent", { x: 320, y: Math.max(0, (Math.max(toolIds.length, kbIds.length, 1) - 1) * 55) }),
        selected: selected?.kind === "agent",
        data: { type: "agent", title: form.name || "Agent", subtitle: form.goal, problems: [], state: runView.steps["agent"], detail: active ? `Calling ${active}…` : null },
      },
    ];
    toolIds.forEach((tid, i) => {
      const name = toolName(tid);
      nodes.push({
        id: `tool:${tid}`,
        type: "step",
        position: at(`tool:${tid}`, { x: 680, y: i * 110 }),
        selected: selected?.kind === "tool" && selected.id === tid,
        data: {
          type: "tool",
          title: name,
          subtitle: "A tool this agent may call",
          problems: [],
          state: active === name ? "running" : runView.usedTools.includes(name) ? "succeeded" : undefined,
        },
      });
    });
    kbIds.forEach((kid, i) => {
      nodes.push({
        id: `kb:${kid}`,
        type: "step",
        position: at(`kb:${kid}`, { x: 0, y: i * 110 }),
        data: { type: "knowledge", title: kbName(kid), subtitle: "Searched when it needs facts", problems: [] },
      });
    });
    return nodes.map((n) => (sizes[n.id] ? { ...n, measured: sizes[n.id] } : n));
  }, [form, toolIds, kbIds, positions, selected, runView, active, sizes]); // eslint-disable-line react-hooks/exhaustive-deps

  const flowEdges: Edge[] = useMemo(
    () => [
      ...toolIds.map((tid) => {
        const on = active === toolName(tid);
        return {
          id: `e:${tid}`,
          source: "agent",
          target: `tool:${tid}`,
          animated: on,
          markerEnd: { type: MarkerType.ArrowClosed },
          style: { stroke: on ? "#38bdf8" : "#a1a1aa", strokeWidth: on ? 2.5 : 1.5 },
        };
      }),
      ...kbIds.map((kid) => ({ id: `k:${kid}`, source: `kb:${kid}`, target: "agent", style: { stroke: "#c4b5fd", strokeDasharray: "4 4" } })),
    ],
    [toolIds, kbIds, active],
  );

  const onNodesChange = useCallback((changes: NodeChange<StepNodeType>[]) => {
    track(changes);
    for (const c of changes) {
      if (c.type === "position" && c.position) setPositions((p) => ({ ...p, [c.id]: c.position! }));
      if (c.type === "select" && c.selected) {
        setSelected(c.id === "agent" ? { kind: "agent" } : c.id.startsWith("tool:") ? { kind: "tool", id: c.id.slice(5) } : null);
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
      <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        <button type="button" onClick={onBack} className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer" aria-label="Back">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <Input aria-label="Agent name" className="h-8 w-56 border-transparent font-semibold hover:border-zinc-200" value={form.name} disabled={readOnly} onChange={(e) => update({ ...form, name: e.target.value })} />
        <span className={cn("text-xs", dirty ? "text-amber-600" : "text-zinc-400")}>{readOnly ? "View only — shared by a teammate" : dirty ? "Unsaved changes" : "Saved"}</span>
        <div className="ml-auto flex gap-2">
          {!readOnly && (
            <Button
              size="sm"
              variant="outline"
              className={cn("h-8", selected?.kind === "publish" && "bg-indigo-50")}
              onClick={() => setSelected(selected?.kind === "publish" ? null : { kind: "publish" })}
            >
              <Globe /> Publish
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            className={cn("h-8", selected?.kind === "tests" && "bg-indigo-50")}
            onClick={() => setSelected(selected?.kind === "tests" ? null : { kind: "tests" })}
          >
            <FlaskConical /> Tests
          </Button>
          <Button
            size="sm"
            variant="outline"
            className={cn("h-8", selected?.kind === "history" && "bg-indigo-50")}
            onClick={() => setSelected(selected?.kind === "history" ? null : { kind: "history" })}
          >
            <History /> History
          </Button>
          <Button size="sm" variant="outline" className={cn("h-8", playOpen && "bg-indigo-50")} onClick={() => setPlayOpen((o) => !o)}>
            <Play /> Test
          </Button>
          {!readOnly && (
            <Button size="sm" className="h-8" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Spinner className="h-4 w-4" /> : <Save />} Save
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
                <div className="absolute inset-y-0 right-0 z-10 w-96 border-l border-zinc-200 bg-white shadow-lg">
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
              {selected?.kind === "tests" && (
                <div className="absolute inset-y-0 right-0 z-10 w-96 border-l border-zinc-200 bg-white shadow-lg">
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
                <div className="absolute inset-y-0 right-0 z-10 w-80 border-l border-zinc-200 bg-white shadow-lg">
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
              {selected && (selected.kind === "agent" || selected.kind === "tool") && (
                <div className="absolute inset-y-0 right-0 z-10 w-80 overflow-y-auto border-l border-zinc-200 bg-white shadow-lg">
                  <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
                    <h2 className="text-sm font-semibold text-zinc-900">{selected.kind === "agent" ? "Agent" : "Tool"}</h2>
                    <button type="button" aria-label="Close" onClick={() => setSelected(null)} className="text-zinc-400 hover:text-zinc-700 cursor-pointer"><X className="h-4 w-4" /></button>
                  </div>
                  {selected.kind === "agent" ? (
                    <>
                      <AgentFields value={form} token={token} readOnly={readOnly} onChange={update} />
                      <AgentSchedules agentId={id} token={token} />
                    </>
                  ) : (
                    <ToolPanel
                      toolId={selected.id}
                      token={token}
                      readOnly={readOnly}
                      onRemove={() => {
                        update({ ...form, config: { ...form.config, tool_ids: toolIds.filter((t) => t !== selected.id) } });
                        setSelected({ kind: "agent" });
                      }}
                    />
                  )}
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
              stepName={() => form.name || "Agent"}
              onClose={() => {
                setPlayOpen(false);
                setRunView(emptyRunView);
              }}
            />
          }
        />
      </div>
    </div>
  );
}

function ToolPanel({ toolId, token, readOnly, onRemove }: { toolId: string; token: string; readOnly: boolean; onRemove: () => void }) {
  const serverId = serverIdOf(toolId);
  const server = useQuery({ queryKey: ["builder-server-tools", serverId], queryFn: () => builderApi.serverTools(token, serverId!), enabled: !!token && !!serverId });
  const tool = server.data?.tools.find((t) => t.name === toolName(toolId));
  return (
    <div className="space-y-3 p-4">
      {server.isLoading && <Spinner className="h-4 w-4 text-zinc-400" />}
      <div className="flex items-center gap-1.5">
        <p className="text-sm font-semibold text-zinc-900">{server.data ? `${server.data.server_name}.` : ""}{toolName(toolId)}</p>
        {tool && <RiskBadge risk={tool.risk.risk} />}
      </div>
      {tool?.description && <p className="text-xs text-zinc-500">{tool.description}</p>}
      {server.data && !server.data.connected && (
        <p className="rounded bg-amber-50 p-2 text-xs text-amber-800">
          Connect {server.data.server_name} before running — <a className="underline" href="/user/agents">open connections</a>.
        </p>
      )}
      {server.isError && <p className="text-xs text-red-600">This tool&apos;s server is no longer available.</p>}
      {!readOnly && (
        <Button variant="outline" size="sm" className="w-full text-red-600" onClick={onRemove}>
          <Trash2 /> Remove from agent
        </Button>
      )}
    </div>
  );
}
