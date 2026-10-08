"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, ArrowLeft, Bot, Check, Play, Plus, Save, Settings, Sparkles } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { EdgeInspector, SettingsPanel, StepInspector } from "@/components/builder/inspector";
import { Playground } from "@/components/builder/playground";
import { SplitPane } from "@/components/builder/split-pane";
import { nodeTypes, useNodeSizes, type StepNodeType } from "@/components/builder/step-node";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import {
  NODE_META,
  PALETTE,
  connect,
  draftKey,
  forSave,
  inputFields,
  newNode,
  problemsByStep,
  removeSteps,
  stepSubtitle,
  stepTitle,
  updateStep,
} from "@/lib/builder/graph";
import { emptyRunView, type RunView } from "@/lib/builder/run-state";
import type { Agent, Problem, WorkflowConfig, WorkflowEdge, WorkflowNode } from "@/lib/builder/types";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

interface Doc {
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  config: WorkflowConfig;
  version: number;
}

type Selection = { kind: "node"; id: string } | { kind: "edge"; id: string } | { kind: "settings" } | null;
type Notice = { tone: "ok" | "warn" | "error"; text: string; detail?: string[]; reload?: boolean } | null;

export default function WorkflowEditorPage() {
  return (
    <ProtectedDashboard path="/user" title="Workflow" description="Build and test a workflow" fullBleed>
      <ReactFlowProvider>
        <WorkflowEditor />
      </ReactFlowProvider>
    </ProtectedDashboard>
  );
}

function WorkflowEditor() {
  const { id } = useParams<{ id: string }>();
  const token = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const flow = useReactFlow();

  const wfQuery = useQuery({ queryKey: ["builder-workflow", id], queryFn: () => builderApi.getWorkflow(token, id), enabled: !!token });
  const agentsQuery = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token });

  const [doc, setDoc] = useState<Doc | null>(null);
  const [dirty, setDirty] = useState(false);
  const [selection, setSelection] = useState<Selection>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [notice, setNotice] = useState<Notice>(null);
  const [playOpen, setPlayOpen] = useState(false);
  const [runView, setRunView] = useState<RunView>(emptyRunView);
  const [instruction, setInstruction] = useState("");
  const loaded = useRef(false);

  // First load: the saved workflow, or an AI draft handed over from the studio.
  useEffect(() => {
    const wf = wfQuery.data;
    if (!wf || loaded.current) return;
    loaded.current = true;
    let next: Doc = { name: wf.name, nodes: wf.nodes, edges: wf.edges, config: wf.config, version: wf.version };
    try {
      const raw = window.sessionStorage.getItem(draftKey(id));
      if (raw) {
        const draft = JSON.parse(raw);
        next = { ...next, name: draft.name ?? next.name, nodes: draft.nodes, edges: draft.edges, config: draft.config ?? next.config };
        setDirty(true);
        setProblems(draft.problems ?? []);
        const connectNames: string[] = (draft.needs_connection ?? []).map((s: { server_name: string }) => s.server_name);
        setNotice({
          tone: "warn",
          text: "This is the AI's draft — review the steps, then Save.",
          detail: connectNames.length ? [`Connect before running: ${connectNames.join(", ")}`] : undefined,
        });
      }
    } catch {
      /* no draft */
    }
    setDoc(next);
  }, [wfQuery.data, id]);

  const agentsById = useMemo(() => {
    const map: Record<string, Agent> = {};
    for (const a of agentsQuery.data ?? []) map[a.id] = a;
    for (const a of wfQuery.data?.agents ?? []) map[a.id] = a;
    return map;
  }, [agentsQuery.data, wfQuery.data]);

  const change = useCallback((fn: (d: Doc) => Doc) => {
    setDoc((d) => (d ? fn(d) : d));
    setDirty(true);
  }, []);

  // Live checks against the backend as the graph changes.
  useEffect(() => {
    if (!doc || !token) return;
    const t = setTimeout(async () => {
      try {
        const res = await builderApi.validateWorkflow(token, { nodes: forSave(doc.nodes), edges: doc.edges, config: doc.config, workflow_id: id });
        setProblems(res.problems);
      } catch {
        /* a graph pydantic rejects outright: saving shows why */
      }
    }, 700);
    return () => clearTimeout(t);
  }, [doc?.nodes, doc?.edges, doc?.config, token, id]); // eslint-disable-line react-hooks/exhaustive-deps

  const { byStep, general } = useMemo(() => problemsByStep(problems), [problems]);

  const save = useMutation({
    mutationFn: () =>
      builderApi.updateWorkflow(token, id, {
        name: doc!.name,
        nodes: forSave(doc!.nodes),
        edges: doc!.edges,
        config: doc!.config,
        expected_version: doc!.version,
      }),
    onSuccess: (wf) => {
      setDoc({ name: wf.name, nodes: wf.nodes, edges: wf.edges, config: wf.config, version: wf.version });
      setDirty(false);
      setProblems([]);
      setNotice({ tone: "ok", text: "Saved." });
      try {
        window.sessionStorage.removeItem(draftKey(id));
      } catch {
        /* ignore */
      }
      queryClient.setQueryData(["builder-workflow", id], wf);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 422) {
        const list = (err.body as { problems?: Problem[] })?.problems ?? [];
        setProblems(list);
        setNotice({ tone: "error", text: "Not saved — fix the marked steps first.", detail: list.filter((p) => !p.node_id).map((p) => p.message) });
      } else if (err instanceof ApiError && err.status === 409) {
        setNotice({ tone: "error", text: err.message, reload: true });
      } else {
        setNotice({ tone: "error", text: err instanceof Error ? err.message : "Couldn't save." });
      }
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

  const aiEdit = useMutation({
    mutationFn: () =>
      builderApi.editWorkflow(token, { instruction, name: doc!.name, nodes: doc!.nodes, edges: doc!.edges, config: doc!.config, workflow_id: id }),
    onSuccess: (res) => {
      if (res.changes.length) {
        change((d) => ({ ...d, name: res.name, nodes: res.nodes, edges: res.edges, config: res.config }));
        setProblems(res.problems);
        setInstruction("");
      }
      setNotice({
        tone: res.warnings.length ? "warn" : "ok",
        text: res.answer ?? res.summary ?? (res.changes.length ? "Changed." : "Nothing to change."),
        detail: [...res.changes, ...res.warnings],
      });
    },
    onError: (err) => setNotice({ tone: "error", text: err instanceof Error ? err.message : "The AI couldn't make that change." }),
  });

  const { sizes, track } = useNodeSizes();
  const flowNodes: StepNodeType[] = useMemo(
    () =>
      (doc?.nodes ?? []).map((n) => ({
        id: n.id,
        type: "step",
        position: n.position ?? { x: 0, y: 0 },
        measured: sizes[n.id],
        selected: selection?.kind === "node" && selection.id === n.id,
        data: {
          type: n.type,
          title: stepTitle(n, agentsById),
          subtitle: stepSubtitle(n, agentsById),
          problems: byStep[n.id] ?? [],
          state: runView.steps[n.id],
          detail: runView.activeTool[n.id] ? `Calling ${runView.activeTool[n.id]}…` : null,
        },
      })),
    [doc?.nodes, selection, agentsById, byStep, runView, sizes],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      (doc?.edges ?? []).map((e) => {
        const flowing = runView.steps[e.source] === "succeeded" && runView.steps[e.target] === "running";
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.condition ?? undefined,
          selected: selection?.kind === "edge" && selection.id === e.id,
          animated: flowing,
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          style: { strokeWidth: flowing ? 2.5 : 1.5, stroke: flowing ? "#38bdf8" : "#a1a1aa" },
          labelStyle: { fontSize: 11, fontWeight: 600 },
          labelBgStyle: { fill: "#fef3c7" },
        };
      }),
    [doc?.edges, selection, runView],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<StepNodeType>[]) => {
      track(changes);
      const moved = changes.filter((c) => c.type === "position" && c.position);
      if (moved.length) {
        change((d) => ({
          ...d,
          nodes: d.nodes.map((n) => {
            const c = moved.find((m) => m.type === "position" && m.id === n.id);
            return c && c.type === "position" && c.position ? { ...n, position: c.position } : n;
          }),
        }));
      }
      const removed = changes.filter((c) => c.type === "remove").map((c) => (c.type === "remove" ? c.id : ""));
      if (removed.length) {
        change((d) => ({ ...d, ...removeSteps(d.nodes, d.edges, removed) }));
        setSelection(null);
      }
      const picked = changes.find((c) => c.type === "select" && c.selected);
      if (picked && picked.type === "select") setSelection({ kind: "node", id: picked.id });
    },
    [change, track],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const removed = new Set(changes.filter((c) => c.type === "remove").map((c) => (c.type === "remove" ? c.id : "")));
      if (removed.size) change((d) => ({ ...d, edges: d.edges.filter((e) => !removed.has(e.id)) }));
      const picked = changes.find((c) => c.type === "select" && c.selected);
      if (picked && picked.type === "select") setSelection({ kind: "edge", id: picked.id });
    },
    [change],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return;
      change((d) => ({ ...d, edges: connect(d.nodes, d.edges, c.source, c.target) }));
    },
    [change],
  );

  // The canvas shrinks/grows with the playground: keep the whole graph in view.
  useEffect(() => {
    const t = setTimeout(() => flow.fitView({ padding: 0.25, duration: 200 }), 60);
    return () => clearTimeout(t);
  }, [playOpen, flow]);

  const addStep = (type: (typeof PALETTE)[number]) => {
    if (!doc) return;
    const center = flow.screenToFlowPosition({ x: window.innerWidth * (playOpen ? 0.3 : 0.45), y: window.innerHeight * 0.45 });
    const node = newNode(type, doc.nodes, { x: center.x + Math.random() * 40, y: center.y + Math.random() * 40 });
    change((d) => ({ ...d, nodes: [...d.nodes, node] }));
    setSelection({ kind: "node", id: node.id });
  };

  if (wfQuery.isError) {
    return <Centered text={wfQuery.error instanceof Error ? wfQuery.error.message : "Couldn't load this workflow."} />;
  }
  if (!doc) return <Centered spinner />;

  const selectedNode = selection?.kind === "node" ? doc.nodes.find((n) => n.id === selection.id) : undefined;
  const selectedEdge = selection?.kind === "edge" ? doc.edges.find((e) => e.id === selection.id) : undefined;
  const panelOpen = !!selectedNode || !!selectedEdge || selection?.kind === "settings";
  const problemCount = problems.length;
  const standalone = (agentsQuery.data ?? []).filter((a) => !a.workflow_id);

  return (
    <div className="flex h-screen flex-col bg-zinc-50">
      <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        <a href="/user/projects" className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900" aria-label="Back to projects">
          <ArrowLeft className="h-4 w-4" />
        </a>
        <Input
          aria-label="Workflow name"
          className="h-8 w-56 border-transparent font-semibold hover:border-zinc-200"
          value={doc.name}
          onChange={(e) => change((d) => ({ ...d, name: e.target.value }))}
        />
        <span className={cn("text-xs", dirty ? "text-amber-600" : "text-zinc-400")}>{dirty ? "Unsaved changes" : "Saved"}</span>
        {problemCount > 0 && (
          <span className="flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700" title={problems.map((p) => p.message).join("\n")}>
            <AlertTriangle className="h-3 w-3" /> {problemCount}
          </span>
        )}
        <form
          className="mx-auto flex w-full max-w-xl items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (instruction.trim() && !aiEdit.isPending) aiEdit.mutate();
          }}
        >
          <Sparkles className="h-4 w-4 shrink-0 text-indigo-500" />
          <Input
            className="h-8"
            placeholder="Ask AI to change it — e.g. add a Slack message after the summary"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
          />
          <Button type="submit" size="sm" variant="outline" className="h-8" disabled={!instruction.trim() || aiEdit.isPending}>
            {aiEdit.isPending ? <Spinner className="h-4 w-4" /> : "Apply"}
          </Button>
        </form>
        <Button size="sm" variant="outline" className="h-8" onClick={() => setSelection({ kind: "settings" })}>
          <Settings /> Settings
        </Button>
        <Button size="sm" variant="outline" className={cn("h-8", playOpen && "bg-indigo-50")} onClick={() => setPlayOpen((o) => !o)}>
          <Play /> Test
        </Button>
        <Button size="sm" className="h-8" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? <Spinner className="h-4 w-4" /> : <Save />} Save
        </Button>
      </header>

      {notice && (
        <div
          className={cn(
            "flex items-start gap-2 border-b px-4 py-2 text-xs",
            notice.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : notice.tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-800",
          )}
        >
          {notice.tone === "ok" ? <Check className="mt-0.5 h-3.5 w-3.5" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5" />}
          <div className="flex-1">
            <p className="font-medium">{notice.text}</p>
            {notice.detail?.map((d, i) => <p key={i}>• {d}</p>)}
          </div>
          {notice.reload && (
            <button type="button" className="font-medium underline cursor-pointer" onClick={() => window.location.reload()}>
              Reload
            </button>
          )}
          <button type="button" className="text-current/60 cursor-pointer" aria-label="Dismiss" onClick={() => setNotice(null)}>×</button>
        </div>
      )}
      {general.length > 0 && !notice && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-1.5 text-xs text-red-800">{general.map((p) => p.message).join(" · ")}</div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-44 shrink-0 flex-col gap-1 border-r border-zinc-200 bg-white p-2">
          <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Add a step</p>
          {PALETTE.map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => addStep(type)}
              title={NODE_META[type].hint}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-zinc-700 hover:bg-zinc-100 cursor-pointer"
            >
              <Plus className="h-3.5 w-3.5 text-zinc-400" />
              {NODE_META[type].title}
            </button>
          ))}
          <p className="mt-auto px-1 text-[11px] leading-snug text-zinc-400">
            Drag from a step&apos;s right dot to another step to connect them. Select and press Delete to remove.
          </p>
        </aside>

        <SplitPane
          open={playOpen}
          left={
            <div className="relative h-full">
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onPaneClick={() => setSelection(null)}
                deleteKeyCode={["Backspace", "Delete"]}
                fitView
                fitViewOptions={{ padding: 0.25 }}
                proOptions={{ hideAttribution: true }}
              >
                <Background gap={16} color="#e4e4e7" />
                <Controls showInteractive={false} />
                <MiniMap pannable zoomable nodeColor="#a5b4fc" nodeStrokeColor="#6366f1" maskColor="rgba(244,244,245,0.7)" className="!hidden md:!block" />
              </ReactFlow>
              {doc.nodes.length <= 1 && (
                <div className="pointer-events-none absolute inset-x-0 top-6 mx-auto w-fit rounded-lg bg-white/90 px-4 py-2 text-sm text-zinc-500 shadow-sm">
                  <Bot className="mr-1 inline h-4 w-4 text-indigo-500" />
                  Add steps from the left, or describe the change in the AI box above.
                </div>
              )}
              {panelOpen && (
                <div className="absolute inset-y-0 right-0 z-10 w-80 border-l border-zinc-200 bg-white shadow-lg">
                  {selectedNode && (
                    <StepInspector
                      key={selectedNode.id}
                      node={selectedNode}
                      nodes={doc.nodes}
                      edges={doc.edges}
                      agents={agentsById}
                      standaloneAgents={standalone}
                      problems={byStep[selectedNode.id] ?? []}
                      token={token}
                      onChange={(patch) => change((d) => ({ ...d, nodes: updateStep(d.nodes, selectedNode.id, patch) }))}
                      onEdgeChange={(edgeId, patch) => change((d) => ({ ...d, edges: d.edges.map((e) => (e.id === edgeId ? { ...e, ...patch } : e)) }))}
                      onDelete={() => {
                        change((d) => ({ ...d, ...removeSteps(d.nodes, d.edges, [selectedNode.id]) }));
                        setSelection(null);
                      }}
                      onClose={() => setSelection(null)}
                    />
                  )}
                  {selectedEdge && (
                    <EdgeInspector
                      edge={selectedEdge}
                      fromCondition={doc.nodes.find((n) => n.id === selectedEdge.source)?.type === "condition"}
                      onChange={(patch) => change((d) => ({ ...d, edges: d.edges.map((e) => (e.id === selectedEdge.id ? { ...e, ...patch } : e)) }))}
                      onDelete={() => {
                        change((d) => ({ ...d, edges: d.edges.filter((e) => e.id !== selectedEdge.id) }));
                        setSelection(null);
                      }}
                      onClose={() => setSelection(null)}
                    />
                  )}
                  {selection?.kind === "settings" && (
                    <SettingsPanel config={doc.config} onChange={(config) => change((d) => ({ ...d, config }))} onClose={() => setSelection(null)} />
                  )}
                </div>
              )}
            </div>
          }
          right={
            <Playground
              kind="workflow"
              targetId={id}
              token={token}
              fields={inputFields(doc.nodes)}
              beforeRun={ensureSaved}
              onView={setRunView}
              stepName={(nodeId) => {
                const n = doc.nodes.find((x) => x.id === nodeId);
                return n ? stepTitle(n, agentsById) : nodeId;
              }}
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

function Centered({ text, spinner }: { text?: string; spinner?: boolean }) {
  return (
    <div className="flex h-screen items-center justify-center text-sm text-zinc-500">
      {spinner ? <Spinner className="h-6 w-6" /> : text}
    </div>
  );
}
