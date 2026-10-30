"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle, ArrowLeft, Check, ChevronDown, Eye, MessageSquare,
  Play, Plus, Redo2, RotateCcw, Save, Sparkles, Square, Undo2, Wand2, X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import { Spinner } from "@/components/ui/spinner";
import { ApprovalCard } from "@/components/builder/approval-card";
import { flowEdgeTypes, type FlowEdgeType } from "@/components/builder/flow-edge";
import { CanvasContext, NODE_LOOK, flowNodeTypes, type CanvasCtx, type FlowNodeType } from "@/components/builder/flow-node";
import { EdgeInspector, StepInspector } from "@/components/builder/inspector";
import { Playground } from "@/components/builder/playground";
import { PublishPanel } from "@/components/builder/publish-panel";
import { SplitPane } from "@/components/builder/split-pane";
import { StepTest, canTestStep } from "@/components/builder/step-test";
import { AnswerActions, AnswerView, StepRunPanel } from "@/components/builder/run-output";
import { useNodeSizes } from "@/components/builder/step-node";
import { TestsPanel } from "@/components/builder/tests-panel";
import { VersionHistory, timeAgo } from "@/components/builder/version-history";
import { TypeIcon } from "@/components/builder/type-icon";
import { WorkflowSettings } from "@/components/builder/workflow-settings";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { arrange } from "@/lib/builder/arrange";
import { connect, draftKey, duplicateStep, forSave, inputFields, insertAfter, newNode, problemsByStep, removeSteps, stepTitle, unsavedKey, updateStep } from "@/lib/builder/graph";
import { emptyRunView, isFinished, type RunView } from "@/lib/builder/run-state";
import type { Agent, AnswerDepth, NodeType, Problem, RunNode, WorkflowConfig, WorkflowEdge, WorkflowNode } from "@/lib/builder/types";
import type { BuildTarget } from "@/lib/builder/use-builder-actions";
import { useRunStream } from "@/lib/builder/use-run-stream";
import { useStreamPref } from "@/lib/builder/stream-pref";
import { StreamToggle } from "@/components/builder/stream-toggle";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

interface Doc {
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  config: WorkflowConfig;
  version: number;
}

type Selection =
  /** ``open``: its settings are showing (a click only selects it, which shows its toolbar). */
  | { kind: "node"; id: string; open?: boolean }
  | { kind: "edge"; id: string }
  | { kind: "settings" }
  | { kind: "history" }
  | { kind: "tests" }
  | { kind: "publish" }
  | null;
type Notice = { tone: "ok" | "warn" | "error"; text: string; detail?: string[]; reload?: boolean } | null;

/** Everything "Add Step" offers, in Marketplace's order. */
const ADDABLE: NodeType[] = ["input", "manual_trigger", "schedule_trigger", "agent", "condition", "output", "tool", "human_approval", "join"];
const DRAG_TYPE = "application/x-builder-step";
const CHIPS = ["Add a human approval before the last step", "Retry each step up to 3 times if it fails", "Notify me on Slack when it finishes"];
const DEPTHS: { value: AnswerDepth; label: string; hint: string }[] = [
  { value: "short", label: "Short", hint: "A sentence or two" },
  { value: "auto", label: "Auto", hint: "Sized to the question" },
  { value: "detailed", label: "Detailed", hint: "In depth, with the reasoning" },
];
type EditorProps = {
  id: string;
  onBack: () => void;
  onSwitch?: (workflowId: string) => void;
  /** Kept for callers; the editor has no build bar any more, so it opens and leaves nothing through these. */
  onOpen: (target: BuildTarget) => void;
  onExit?: () => void;
};

/** The workflow canvas (same chrome as the agent editor) for one saved workflow. */
export function WorkflowEditor(props: EditorProps) {
  return (
    <ReactFlowProvider>
      <Editor {...props} />
    </ReactFlowProvider>
  );
}

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = window.localStorage.getItem(key);
    return v && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
  } catch {
    return fallback;
  }
}

/** How many editors have each workflow open (a page can swap one for another). */
const openEditors = new Map<string, number>();

function Editor({ id, onBack, onSwitch }: EditorProps) {
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
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [depth, setDepthState] = useState<AnswerDepth>("auto");
  const [streamOn] = useStreamPref();
  const [inputText, setInputTextState] = useState("");
  // A run started from the canvas (Run / the AI bar), shown on the nodes.
  const [canvasRunId, setCanvasRunId] = useState<string | null>(null);
  const [runCardOpen, setRunCardOpen] = useState(false);
  // The step being tried on its own (the toolbar's Test).
  const [testId, setTestId] = useState<string | null>(null);
  // The step whose last answer is showing (its Result).
  const [resultId, setResultId] = useState<string | null>(null);
  const loaded = useRef(false);
  const inputKey = `builder.input.${id}`;

  // Made by "blank" / "with AI" and never saved: delete it on the way out, so
  // only workflows someone actually saved are listed.
  const version = useRef<number | null>(null);
  version.current = doc?.version ?? version.current;
  useEffect(() => {
    openEditors.set(id, (openEditors.get(id) ?? 0) + 1);
    return () => {
      openEditors.set(id, (openEditors.get(id) ?? 1) - 1);
      // Deferred so a remount (Strict Mode, the page swapping layouts) keeps it.
      setTimeout(() => {
        if (openEditors.get(id)) return;
        let created: string | null = null;
        try {
          created = window.sessionStorage.getItem(unsavedKey(id));
        } catch {
          return;
        }
        if (created === null) return;
        window.sessionStorage.removeItem(unsavedKey(id));
        if (version.current !== null && version.current > Number(created)) return; // saved since
        window.sessionStorage.removeItem(draftKey(id));
        void builderApi.deleteWorkflow(token, id).finally(() => queryClient.invalidateQueries({ queryKey: ["builder-workflows"] }));
      }, 0);
    };
  }, [id, token, queryClient]);

  useEffect(() => {
    setDepthState(readStored("answerDepth", ["auto", "short", "detailed"] as const, "auto"));
    try {
      setInputTextState(window.sessionStorage.getItem(inputKey) ?? "");
    } catch {
      /* none */
    }
  }, [inputKey]);
  const setDepth = (d: AnswerDepth) => {
    setDepthState(d);
    try {
      window.localStorage.setItem("answerDepth", d);
    } catch {
      /* not remembered */
    }
  };
  const setInputText = useCallback((text: string) => {
    setInputTextState(text);
    try {
      window.sessionStorage.setItem(inputKey, text);
    } catch {
      /* not remembered */
    }
  }, [inputKey]);

  // First load: the saved workflow, or an AI draft handed over from the compiler.
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

  // Undo / redo: every change keeps the graph it replaced. Changes with the
  // same ``key`` close together (a drag, typing in one step) count as one.
  const docRef = useRef<Doc | null>(null);
  docRef.current = doc;
  const past = useRef<Doc[]>([]);
  const future = useRef<Doc[]>([]);
  const lastChange = useRef<{ key: string; at: number } | null>(null);
  const [historySize, setHistorySize] = useState({ past: 0, future: 0 });
  const change = useCallback((fn: (d: Doc) => Doc, key?: string) => {
    const d = docRef.current;
    if (!d) return;
    const next = fn(d);
    if (next === d) return;
    const now = Date.now();
    const last = lastChange.current;
    if (!(key && last?.key === key && now - last.at < 1000)) {
      past.current = [...past.current.slice(-49), d];
      future.current = [];
    }
    lastChange.current = key ? { key, at: now } : null;
    docRef.current = next;
    setDoc(next);
    setDirty(true);
    setHistorySize({ past: past.current.length, future: 0 });
  }, []);
  const step = useCallback((from: React.MutableRefObject<Doc[]>, to: React.MutableRefObject<Doc[]>) => {
    const d = docRef.current;
    const back = from.current.at(-1);
    if (!d || !back) return;
    from.current = from.current.slice(0, -1);
    to.current = [...to.current, d];
    lastChange.current = null;
    // The graph comes back; the saved version it's checked against stays current.
    const next = { ...back, version: d.version };
    docRef.current = next;
    setDoc(next);
    setDirty(true);
    setHistorySize({ past: past.current.length, future: future.current.length });
  }, []);
  const undo = useCallback(() => step(past, future), [step]);
  const redo = useCallback(() => step(future, past), [step]);
  const canEdit = !!wfQuery.data?.can_manage && previewVersion === null;
  useEffect(() => {
    if (!canEdit) return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const el = e.target as HTMLElement | null;
      // Typing keeps the field's own undo.
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) undo();
      else if ((k === "z" && e.shiftKey) || k === "y") redo();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canEdit, undo, redo]);

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

  const previewQuery = useQuery({
    queryKey: ["builder-version", "workflow", id, previewVersion],
    queryFn: () => builderApi.getVersion(token, "workflow", id, previewVersion!),
    enabled: !!token && previewVersion !== null,
    staleTime: Infinity, // a saved version never changes
  });
  const preview = previewVersion !== null ? previewQuery.data ?? null : null;
  const previewing = previewVersion !== null;
  const shown = preview ? { nodes: preview.snapshot.nodes ?? [], edges: preview.snapshot.edges ?? [] } : doc;
  const shownAgents = useMemo(
    () => (preview?.snapshot.agents ? { ...agentsById, ...(preview.snapshot.agents as unknown as Record<string, Agent>) } : agentsById),
    [preview, agentsById],
  );

  const save = useMutation({
    mutationFn: () =>
      builderApi.updateWorkflow(token, id, { name: doc!.name, nodes: forSave(doc!.nodes), edges: doc!.edges, config: doc!.config, expected_version: doc!.version }),
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
      for (const key of [["builder-versions", "workflow", id], ["builder-schedules", "workflow", id], ["builder-workflows"]]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
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
    mutationFn: (text: string) =>
      builderApi.editWorkflow(token, { instruction: text, name: doc!.name, nodes: doc!.nodes, edges: doc!.edges, config: doc!.config, workflow_id: id }),
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

  const improve = useMutation({
    mutationFn: () => builderApi.improveText(token, "prompt", instruction, `An instruction to change the workflow "${doc?.name}".`),
    onSuccess: (r) => setInstruction(r.text),
  });

  const restore = useMutation({
    mutationFn: (version: number) => builderApi.restoreWorkflowVersion(token, id, version, doc!.version),
    onSuccess: (wf, version) => {
      setDoc({ name: wf.name, nodes: wf.nodes, edges: wf.edges, config: wf.config, version: wf.version });
      setDirty(false);
      setProblems([]);
      setPreviewVersion(null);
      setNotice({ tone: "ok", text: `Version ${version} is back (saved as version ${wf.version}).` });
      try {
        window.sessionStorage.removeItem(draftKey(id));
      } catch {
        /* ignore */
      }
      queryClient.setQueryData(["builder-workflow", id], wf);
      for (const key of [["builder-versions", "workflow", id], ["builder-schedules", "workflow", id], ["builder-agents"]]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setNotice({ tone: "error", text: err.message, reload: true });
        return;
      }
      const list = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Couldn't restore that version.", detail: list.map((p) => p.message) });
    },
  });

  // ── running from the canvas ──
  const canvasRun = useRunStream(canvasRunId, token);
  const liveView = playOpen ? runView : canvasRunId ? canvasRun.view : emptyRunView;
  // Each step's answer, input and tool calls: from the run on screen (canvas or playground), else this
  // workflow's latest run — so they're there after a reload too. Refetched as steps finish, not only at the end.
  const latestRun = useQuery({
    queryKey: ["builder-runs", "latest", id],
    queryFn: () => builderApi.listRuns(token, { workflow_id: id, limit: 1 }),
    enabled: !!token && !canvasRunId && !runView.runId,
  });
  const resultRunId = (playOpen ? runView.runId : null) ?? canvasRunId ?? runView.runId ?? latestRun.data?.[0]?.id ?? null;
  const settled = Object.values(liveView.steps).filter((st) => st === "succeeded" || st === "failed" || st === "waiting").length;
  const runSnapshot = useQuery({
    queryKey: ["builder-run", resultRunId, settled, liveView.status],
    queryFn: () => builderApi.getRun(token, resultRunId!),
    enabled: !!token && !!resultRunId,
    placeholderData: (prev) => (prev?.id === resultRunId ? prev : undefined),
  });
  const runNodes = useMemo(() => {
    // The latest attempt of each step.
    const map: Record<string, RunNode> = {};
    for (const n of runSnapshot.data?.nodes ?? []) if (!map[n.node_id] || n.attempt >= map[n.node_id].attempt) map[n.node_id] = n;
    return map;
  }, [runSnapshot.data]);
  const outputs = useMemo(() => {
    const map: Record<string, string> = {};
    for (const n of Object.values(runNodes)) if (n.output_text) map[n.node_id] = n.output_text;
    return map;
  }, [runNodes]);
  const trigger = doc?.nodes.find((n) => n.type === "input" || n.type === "manual_trigger" || n.type === "schedule_trigger");

  const startRun = useMutation({
    mutationFn: async (text: string) => {
      if (!(await ensureSaved())) throw new Error("Save the changes first: a run uses the saved workflow.");
      if (inputFields(doc!.nodes).some((f) => f.required)) {
        setPlayOpen(true); // it needs input fields filled in: the playground asks for them
        return null;
      }
      // A chat of its own, so the run shows in Executions → Chat history too.
      return builderApi.startWorkflowRun(token, id, text, {}, depth, { new_conversation: true }, streamOn);
    },
    onSuccess: (run) => {
      if (!run) return;
      void queryClient.invalidateQueries({ queryKey: ["builder-chats", "workflow", id] });
      setCanvasRunId(run.id);
      setRunCardOpen(true);
      setSelection(null);
    },
    onError: (err) => {
      const list = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Couldn't start the run.", detail: list.map((p) => p.message) });
    },
  });
  const stopRun = useMutation({ mutationFn: () => builderApi.cancelRun(token, canvasRunId!) });
  const running = !!canvasRunId && !isFinished(canvasRun.view.status);
  // ── canvas ──
  const { sizes, track } = useNodeSizes();
  const flowNodes: FlowNodeType[] = useMemo(
    () =>
      (shown?.nodes ?? []).map((n) => ({
        id: n.id,
        type: "flow",
        position: n.position ?? { x: 0, y: 0 },
        measured: sizes[n.id],
        selected: !previewing && selection?.kind === "node" && selection.id === n.id,
        data: {
          node: n,
          title: stepTitle(n, shownAgents),
          problems: previewing ? [] : byStep[n.id] ?? [],
          state: previewing ? undefined : liveView.steps[n.id],
          detail: !previewing && liveView.activeTool[n.id] ? `Calling ${liveView.activeTool[n.id]}…` : null,
          // A trigger's "output" is just the request it was given.
          output: previewing || n.type === "input" || n.type === "manual_trigger" || n.type === "schedule_trigger" ? null : outputs[n.id] ?? null,
        },
      })),
    [shown?.nodes, selection, shownAgents, byStep, liveView, sizes, previewing, outputs],
  );

  const canEditLines = !previewing && !!wfQuery.data?.can_manage;
  const removeLine = useCallback((edgeId: string) => {
    change((d) => ({ ...d, edges: d.edges.filter((e) => e.id !== edgeId) }));
    setSelection((s) => (s?.kind === "edge" && s.id === edgeId ? null : s));
  }, [change]);
  const flowEdges: FlowEdgeType[] = useMemo(
    () =>
      (shown?.edges ?? []).map((e) => {
        const flowing = !previewing && liveView.steps[e.source] === "succeeded" && liveView.steps[e.target] === "running";
        const done = !previewing && liveView.steps[e.source] === "succeeded" && !!liveView.steps[e.target];
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          selected: selection?.kind === "edge" && selection.id === e.id,
          animated: flowing,
          type: "flow" as const,
          data: { branch: e.condition ?? null, onDelete: canEditLines ? removeLine : undefined },
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: flowing ? "#38bdf8" : done ? "#34d399" : "#818cf8" },
          style: { strokeWidth: flowing ? 2.5 : 2, stroke: flowing ? "#38bdf8" : done ? "#34d399" : "#6366f1" },
        };
      }),
    [shown?.edges, selection, liveView, previewing, canEditLines, removeLine],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNodeType>[]) => {
      track(changes);
      if (previewing) return;
      const moved = changes.filter((c) => c.type === "position" && c.position);
      if (moved.length) {
        change((d) => ({
          ...d,
          nodes: d.nodes.map((n) => {
            const c = moved.find((m) => m.type === "position" && m.id === n.id);
            return c && c.type === "position" && c.position ? { ...n, position: c.position } : n;
          }),
        }), `move:${moved.map((m) => ("id" in m ? m.id : "")).join(",")}`);
      }
      const removed = changes.filter((c) => c.type === "remove").map((c) => (c.type === "remove" ? c.id : ""));
      if (removed.length) {
        change((d) => ({ ...d, ...removeSteps(d.nodes, d.edges, removed) }));
        setSelection(null);
      }
      const picked = changes.find((c) => c.type === "select" && c.selected);
      // Selecting shows the step's toolbar; its settings stay open if they were (on another step).
      if (picked && picked.type === "select") setSelection((s) => ({ kind: "node", id: picked.id, open: s?.kind === "node" && !!s.open }));
    },
    [change, track, previewing],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (previewing) return;
      const removed = new Set(changes.filter((c) => c.type === "remove").map((c) => (c.type === "remove" ? c.id : "")));
      if (removed.size) change((d) => ({ ...d, edges: d.edges.filter((e) => !removed.has(e.id)) }));
      const picked = changes.find((c) => c.type === "select" && c.selected);
      if (picked && picked.type === "select") setSelection({ kind: "edge", id: picked.id });
    },
    [change, previewing],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return;
      change((d) => ({ ...d, edges: connect(d.nodes, d.edges, c.source, c.target) }));
    },
    [change],
  );

  useEffect(() => {
    const t = setTimeout(() => flow.fitView({ padding: 0.25, maxZoom: 1, duration: 200 }), 60);
    return () => clearTimeout(t);
  }, [playOpen, flow]);
  useEffect(() => {
    if (previewVersion !== null && !preview) return;
    const t = setTimeout(() => flow.fitView({ padding: 0.25, maxZoom: 1, duration: 200 }), 80);
    return () => clearTimeout(t);
  }, [previewVersion, preview, flow]);

  // A step whose settings open off screen (or under the popup) is brought into view beside it.
  const canvasRef = useRef<HTMLDivElement>(null);
  const openId = selection?.kind === "node" && selection.open ? selection.id : testId ?? resultId;
  useEffect(() => {
    if (!openId) return;
    const t = setTimeout(() => {
      const n = flow.getNode(openId);
      const box = canvasRef.current?.getBoundingClientRect();
      if (!n || !box) return;
      const zoom = flow.getZoom();
      const w = (n.measured?.width ?? 270) * zoom;
      const h = (n.measured?.height ?? 120) * zoom;
      const p = flow.flowToScreenPosition(n.position);
      const popup = Math.min(372, box.width * 0.5);
      const visible = p.x >= box.left && p.x + w <= box.right - popup && p.y >= box.top && p.y + h <= box.bottom;
      if (visible) return;
      // Centre it in the part of the canvas the popup leaves free.
      const shift = popup / 2 / zoom;
      flow.setCenter(n.position.x + w / zoom / 2 + shift, n.position.y + h / zoom / 2, { zoom, duration: 300 });
    }, 60);
    return () => clearTimeout(t);
  }, [openId, flow]);

  const addStep = (type: NodeType, at?: { x: number; y: number }) => {
    if (!doc) return;
    let spot = at ?? flow.screenToFlowPosition({ x: window.innerWidth * (playOpen ? 0.3 : 0.45), y: window.innerHeight * 0.4 });
    if (!at) {
      // Clicked in: find a free spot near the middle rather than stacking on a step.
      const taken = (p: { x: number; y: number }) => doc.nodes.some((n) => Math.abs((n.position?.x ?? 0) - p.x) < 290 && Math.abs((n.position?.y ?? 0) - p.y) < 190);
      for (let i = 0; i < 12 && taken(spot); i++) spot = { x: spot.x, y: spot.y + 210 };
    }
    const node = newNode(type, doc.nodes, spot);
    change((d) => ({ ...d, nodes: [...d.nodes, node] }));
    setSelection({ kind: "node", id: node.id, open: true });
    setAddOpen(false);
  };
  const tidy = () => {
    change((d) => ({ ...d, nodes: arrange(d.nodes, d.edges) }));
    setTimeout(() => flow.fitView({ padding: 0.25, maxZoom: 1, duration: 300 }), 80);
  };

  const ctx: CanvasCtx = useMemo(
    () => ({
      token,
      readOnly: previewing || !wfQuery.data?.can_manage,
      agents: shownAgents,
      edges: shown?.edges ?? [],
      inputText,
      setInputText,
      patch: (nodeId, p) => change((d) => ({ ...d, nodes: updateStep(d.nodes, nodeId, p) }), `patch:${nodeId}`),
      open: (nodeId) => setSelection({ kind: "node", id: nodeId, open: true }),
      duplicate: (nodeId) => {
        const d = docRef.current;
        const copy = d && duplicateStep(d.nodes, nodeId);
        if (!copy) return;
        change((x) => ({ ...x, nodes: [...x.nodes, copy] }));
        setSelection({ kind: "node", id: copy.id });
      },
      remove: (nodeId) => {
        change((d) => ({ ...d, ...removeSteps(d.nodes, d.edges, [nodeId]) }));
        setSelection(null);
      },
      addAfter: (nodeId, type) => {
        const d = docRef.current;
        const r = d && insertAfter(d.nodes, d.edges, nodeId, type);
        if (!r) return;
        change((x) => ({ ...x, nodes: r.nodes, edges: r.edges }));
        setSelection({ kind: "node", id: r.id, open: true });
      },
      test: (nodeId) => {
        setSelection({ kind: "node", id: nodeId });
        setTestId(nodeId);
      },
      canTest: (n) => canTestStep(n) && !previewing,
      showResult: (nodeId) => {
        setSelection({ kind: "node", id: nodeId });
        setTestId(null);
        setResultId(nodeId);
      },
    }),
    [token, previewing, wfQuery.data?.can_manage, shownAgents, shown?.edges, inputText, setInputText, change],
  );
  // Test stays open only while its step is the one selected (Configure, another step or the pane closes it).
  useEffect(() => {
    const peeking = (id: string | null) => !!id && !(selection?.kind === "node" && selection.id === id && !selection.open);
    if (peeking(testId)) setTestId(null);
    if (peeking(resultId)) setResultId(null);
  }, [selection, testId, resultId]
  );

  const workflows = useQuery({ queryKey: ["builder-workflows"], queryFn: () => builderApi.listWorkflows(token), enabled: !!token && switchOpen });

  if (wfQuery.isError) {
    return <Centered text={wfQuery.error instanceof Error ? wfQuery.error.message : "Couldn't load this workflow."} />;
  }
  if (!doc) return <Centered spinner />;

  const canManage = !!wfQuery.data?.can_manage;
  const selectedNode = selection?.kind === "node" && selection.open ? doc.nodes.find((n) => n.id === selection.id) : undefined;
  const selectedEdge = selection?.kind === "edge" ? doc.edges.find((e) => e.id === selection.id) : undefined;
  const testNode = testId && !previewing ? doc.nodes.find((n) => n.id === testId) : undefined;
  const resultNode = resultId && runNodes[resultId] && !testNode ? doc.nodes.find((n) => n.id === resultId) : undefined;
  const outputNodeId = doc.nodes.find((n) => n.type === "output")?.id;
  // The popup docked right; the canvas run's card steps aside while it shows.
  const panelOpen = !previewing && !!(selectedNode || selectedEdge || testNode || resultNode || selection?.kind === "settings");
  const standalone = (agentsQuery.data ?? []).filter((a) => !a.workflow_id);
  const overrides = doc.config.approval_overrides ?? {};
  const approvalOn = !(overrides.edit === "never" && overrides.delete === "never");
  const drawer = selection?.kind === "history" || selection?.kind === "tests" || selection?.kind === "publish";

  const toggleApproval = () => {
    if (approvalOn && !window.confirm("Tools that change or delete data will run without asking anyone. Turn approvals off?")) return;
    change((d) => ({
      ...d,
      config: { ...d.config, approval_overrides: approvalOn ? { read: "never", edit: "never", delete: "never" } : { read: "default", edit: "default", delete: "default" } },
    }));
  };

  return (
    <CanvasContext.Provider value={ctx}>
      <div className="builder-dark flex h-full w-full flex-col overflow-hidden bg-[var(--bg)]">
        {/* ── header: what it is, then Add step, undo/redo, Test, Run, Save; the rest under ⋯ ── */}
        <header className="flex items-center gap-1.5 border-b border-zinc-200 px-2 py-2 sm:gap-2 sm:px-3">
          <button type="button" onClick={onBack} className="shrink-0 rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer" aria-label="Back">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="relative shrink-0">
            <button type="button" className="flex h-8 items-center gap-1 rounded-md pl-0.5 pr-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer" onClick={() => { setSwitchOpen((o) => !o); setAddOpen(false); }} aria-label="Switch workflow" aria-expanded={switchOpen} title="Switch workflow">
              <TypeIcon kind="workflow" size="sm" /> <ChevronDown className="h-3.5 w-3.5" />
            </button>
            {switchOpen && (
              <div className="absolute left-0 top-10 z-40 max-h-80 w-72 overflow-y-auto rounded-lg border border-zinc-200 bg-[var(--surface-raised)] p-1 shadow-lg">
                {workflows.isLoading && <div className="flex justify-center p-3"><Spinner className="h-4 w-4 text-zinc-400" /></div>}
                {(workflows.data ?? []).map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    onClick={() => {
                      setSwitchOpen(false);
                      if (w.id === id) return;
                      if (dirty && !window.confirm("You have unsaved changes here. Leave anyway?")) return;
                      onSwitch?.(w.id);
                    }}
                    className={cn("flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-zinc-100 cursor-pointer", w.id === id ? "text-zinc-900" : "text-zinc-700")}
                  >
                    <span className="min-w-0 flex-1 truncate">{w.name}</span>
                    {w.id === id ? <Check className="h-4 w-4 shrink-0" /> : <span className="shrink-0 text-xs text-zinc-500">{w.node_count} steps</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
          <Input aria-label="Workflow name" className="h-8 min-w-0 flex-1 border-transparent bg-transparent px-2 font-semibold hover:border-zinc-200 sm:max-w-64" value={doc.name} disabled={!canManage || previewing} onChange={(e) => change((d) => ({ ...d, name: e.target.value }))} />
          <span className={cn("hidden shrink-0 text-xs md:inline", dirty ? "text-amber-700" : "text-zinc-500")}>{!canManage ? "View only — shared by a teammate" : dirty ? "Unsaved changes" : "Saved"}</span>
          {problems.length > 0 && (
            <span className="flex shrink-0 items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700" title={problems.map((p) => p.message).join("\n")}>
              <AlertTriangle className="h-3 w-3" /> {problems.length}
            </span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-1.5">
            {canManage && (
              <Button size="sm" variant="outline" className={cn("px-2 lg:px-3", addOpen && "bg-zinc-100")} disabled={previewing} onClick={() => { setAddOpen((o) => !o); setSwitchOpen(false); }} aria-expanded={addOpen} aria-label="Add step">
                <Plus /> <span className="hidden lg:inline">Add step</span>
              </Button>
            )}
            {canManage && (
              <div className="hidden items-center sm:flex">
                <IconTool label="Undo (Ctrl+Z)" disabled={previewing || !historySize.past} onClick={undo}><Undo2 /></IconTool>
                <IconTool label="Redo (Ctrl+Shift+Z)" disabled={previewing || !historySize.future} onClick={redo}><Redo2 /></IconTool>
              </div>
            )}
            <Button size="sm" variant="outline" className={cn("hidden px-2 sm:inline-flex lg:px-3", playOpen && "bg-zinc-100")} onClick={() => setPlayOpen((o) => !o)} aria-label="Test in a chat" aria-pressed={playOpen}>
              <MessageSquare /> <span className="hidden lg:inline">Test</span>
            </Button>
            {running ? (
              <Button size="sm" variant="outline" className="px-2 lg:px-3" onClick={() => stopRun.mutate()} aria-label="Stop the run">
                <Square className="h-3 w-3 fill-current" /> <span className="hidden lg:inline">Stop</span>
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                className="px-2 lg:px-3"
                onClick={() => startRun.mutate(inputText)}
                disabled={startRun.isPending || previewing || (trigger?.type === "input" && !inputText.trim())}
                aria-label="Run on the canvas"
                title={trigger?.type === "input" && !inputText.trim() ? "Type what it should work on in the Input step first" : "Run it here on the canvas, step by step"}
              >
                {startRun.isPending ? <Spinner className="h-4 w-4" /> : <Play />} <span className="hidden lg:inline">Run</span>
              </Button>
            )}
            {canManage && (
              <Button size="sm" className="px-2 sm:px-3" disabled={!dirty || save.isPending || previewing} onClick={() => save.mutate()} aria-label="Save">
                {save.isPending ? <Spinner className="h-4 w-4" /> : <Save />} <span className="hidden sm:inline">Save</span>
              </Button>
            )}
            <Menu
              label="More actions"
              items={[
                { label: "Test in a chat", checked: playOpen || undefined, onClick: () => setPlayOpen((o) => !o) },
                ...(canManage
                  ? [
                      { label: "Undo", onClick: undo },
                      { label: "Redo", onClick: redo },
                      { label: "Arrange the steps", onClick: tidy, divided: true },
                      { label: "Ask before changing data", checked: approvalOn, onClick: toggleApproval },
                    ]
                  : []),
                { label: "Run settings", divided: true, onClick: () => setSelection(selection?.kind === "settings" ? null : { kind: "settings" }) },
                { label: "Tests", onClick: () => setSelection(selection?.kind === "tests" ? null : { kind: "tests" }) },
                { label: "Version history", onClick: () => setSelection(selection?.kind === "history" ? null : { kind: "history" }) },
                ...(canManage ? [{ label: "Publish", onClick: () => setSelection(selection?.kind === "publish" ? null : { kind: "publish" }) }] : []),
                ...DEPTHS.map((d, i) => ({ label: `Answer: ${d.label}`, checked: depth === d.value, divided: i === 0, onClick: () => setDepth(d.value) })),
              ]}
            />
          </div>
        </header>

        {/* ── notices ── */}
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
        {general.length > 0 && !notice && (
          <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-800">{general.map((p) => p.message).join(" · ")}</div>
        )}
        {previewing && (
          <div className="flex items-center gap-3 border-b border-indigo-200 bg-indigo-50 px-4 py-2 text-xs text-indigo-800">
            <Eye className="h-3.5 w-3.5 shrink-0" />
            <p className="flex-1">
              {preview ? (
                <><span className="font-semibold">Viewing version {preview.version}</span> — {preview.note.toLowerCase()} {timeAgo(preview.created_at)}{preview.author_name ? ` by ${preview.author_name}` : ""}. Look only.</>
              ) : "Loading that version…"}
            </p>
            {preview && canManage && (
              <Button
                size="sm"
                className="h-7"
                disabled={restore.isPending}
                onClick={() => {
                  const warn = dirty ? "\n\nYour unsaved changes will be lost." : "";
                  if (window.confirm(`Bring back version ${preview.version}? It's saved as a new version.${warn}`)) restore.mutate(preview.version);
                }}
              >
                {restore.isPending ? <Spinner className="h-3.5 w-3.5" /> : <RotateCcw />} Restore this version
              </Button>
            )}
            <Button size="sm" variant="outline" className="h-7" onClick={() => setPreviewVersion(null)}>Back to current</Button>
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          <SplitPane
            open={playOpen}
            left={
              <div
                ref={canvasRef}
                className="relative h-full"
                onDragOver={(e) => {
                  if (e.dataTransfer.types.includes(DRAG_TYPE)) e.preventDefault();
                }}
                onDrop={(e) => {
                  const type = e.dataTransfer.getData(DRAG_TYPE) as NodeType;
                  if (!type) return;
                  e.preventDefault();
                  addStep(type, flow.screenToFlowPosition({ x: e.clientX - 135, y: e.clientY - 40 }));
                }}
              >
                <ReactFlow
                  nodes={flowNodes}
                  edges={flowEdges}
                  edgeTypes={flowEdgeTypes}
                  nodeTypes={flowNodeTypes}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onConnect={onConnect}
                  onNodeDoubleClick={(_, n) => !previewing && setSelection({ kind: "node", id: n.id, open: true })}
                  onPaneClick={() => {
                    if (previewing) return;
                    setSelection((s) => (s && (s.kind === "node" || s.kind === "edge") ? null : s));
                    setAddOpen(false);
                    setSwitchOpen(false);
                  }}
                  nodesDraggable={!previewing && canManage}
                  nodesConnectable={!previewing && canManage}
                  elementsSelectable={!previewing}
                  deleteKeyCode={previewing || !canManage ? null : ["Backspace", "Delete"]}
                  colorMode="dark"
                  fitView
                  fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
                  proOptions={{ hideAttribution: true }}
                >
                  <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#3f3f46" />
                  <Controls showInteractive />
                  <MiniMap
                    pannable
                    zoomable
                    className="!hidden !rounded-xl !border !border-white/10 md:!block"
                    style={{ background: "#18181b" }}
                    maskColor="rgba(9,9,11,0.6)"
                    nodeColor={(n) => ({ input: "#0ea5e9", manual_trigger: "#3b82f6", schedule_trigger: "#14b8a6", agent: "#8b5cf6", tool: "#f97316", condition: "#eab308", join: "#64748b", human_approval: "#f43f5e", output: "#10b981", code: "#71717a" })[(n.data as { node: WorkflowNode }).node.type] ?? "#6366f1"}
                  />
                </ReactFlow>

                {/* ── Add Step palette ── */}
                {addOpen && canManage && (
                  <div className="absolute inset-y-0 left-0 z-30 w-full overflow-y-auto border-r border-zinc-200 bg-[var(--surface)] shadow-lg sm:w-72">
                    <div className="flex items-center justify-between px-4 pb-2 pt-3">
                      <h2 className="text-base font-semibold text-zinc-900">Add a step</h2>
                      <button type="button" aria-label="Close" onClick={() => setAddOpen(false)} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"><X className="h-4 w-4" /></button>
                    </div>
                    <div className="space-y-1 p-2">
                      {ADDABLE.map((type) => {
                        const look = NODE_LOOK[type];
                        return (
                          <div
                            key={type}
                            role="button"
                            tabIndex={0}
                            draggable
                            onDragStart={(e) => { e.dataTransfer.setData(DRAG_TYPE, type); e.dataTransfer.effectAllowed = "copy"; }}
                            onClick={() => addStep(type)}
                            onKeyDown={(e) => e.key === "Enter" && addStep(type)}
                            className="flex cursor-pointer items-center gap-3 rounded-lg p-2 hover:bg-zinc-50"
                          >
                            <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br text-white", look.head)}><look.Icon className="h-4 w-4" /></span>
                            <span className="min-w-0">
                              <span className="block text-sm font-medium text-zinc-900">{look.label}</span>
                              <span className="block truncate text-xs text-zinc-500">{look.hint}</span>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                    <p className="pb-3 text-center text-xs text-zinc-500">Click, or drag onto the canvas</p>
                  </div>
                )}

                {/* ── the open step / line / settings, docked right ── */}
                {panelOpen && (
                  <div
                    className={cn(
                      "absolute z-30 bg-[var(--surface)] shadow-xl",
                      selection?.kind === "settings"
                        ? "inset-y-0 right-0 w-full overflow-y-auto border-l border-zinc-200 p-4 sm:w-[410px]"
                        // A step or a line: a popup over the canvas, as tall as it needs.
                        : "right-3 top-3 flex max-h-[calc(100%-1.5rem)] w-[min(360px,calc(100%-1.5rem))] flex-col overflow-hidden rounded-xl border border-zinc-200",
                    )}
                  >
                    {resultNode && (
                      <StepRunPanel
                        key={resultNode.id}
                        title={stepTitle(resultNode, agentsById)}
                        kind={NODE_LOOK[resultNode.type].label}
                        node={runNodes[resultNode.id]}
                        calls={(runSnapshot.data?.tool_calls ?? []).filter((c) => c.node_id === resultNode.id)}
                        onClose={() => setResultId(null)}
                      />
                    )}
                    {testNode && (
                      <StepTest
                        key={testNode.id}
                        workflowId={id}
                        node={testNode}
                        title={stepTitle(testNode, agentsById)}
                        token={token}
                        initialInput={inputText}
                        onClose={() => setTestId(null)}
                      />
                    )}
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
                        workflowId={id}
                        lastRunId={resultRunId}
                        onChange={(patch) => change((d) => ({ ...d, nodes: updateStep(d.nodes, selectedNode.id, patch) }), `patch:${selectedNode.id}`)}
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
                      <WorkflowSettings workflowId={id} config={doc.config} token={token} canManage={canManage} onChange={(config) => change((d) => ({ ...d, config }))} onClose={() => setSelection(null)} />
                    )}
                  </div>
                )}

                {/* ── history / tests / publish drawer ── */}
                {drawer && (
                  <div className="absolute inset-y-0 right-0 z-30 w-full overflow-hidden border-l border-zinc-200 bg-[var(--surface)] shadow-lg sm:w-96">
                    {selection?.kind === "history" && (
                      <VersionHistory
                        kind="workflow" targetId={id} token={token} canRestore={canManage} dirty={dirty}
                        previewing={previewVersion} restoring={restore.isPending} onPreview={setPreviewVersion}
                        onRestore={(v) => restore.mutate(v)} onClose={() => { setSelection(null); setPreviewVersion(null); }}
                      />
                    )}
                    {!previewing && selection?.kind === "tests" && (
                      <TestsPanel kind="workflow" targetId={id} token={token} canManage={canManage} beforeRun={ensureSaved} onClose={() => setSelection(null)} />
                    )}
                    {!previewing && selection?.kind === "publish" && (
                      <PublishPanel kind="workflow" targetId={id} name={doc.name} token={token} currentVersion={doc.version} dirty={dirty} onClose={() => setSelection(null)} />
                    )}
                  </div>
                )}

                {/* ── the canvas run ── */}
                {canvasRunId && runCardOpen && !playOpen && !panelOpen && (
                  <div className="absolute bottom-3 right-3 z-20 w-96 max-w-[calc(100%-1.5rem)] rounded-xl border border-zinc-200 bg-[var(--surface-raised)] p-3 shadow-lg">
                    <div className="mb-2 flex items-center gap-2">
                      <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize",
                        canvasRun.view.status === "succeeded" ? "bg-emerald-100 text-emerald-700" : canvasRun.view.status === "failed" ? "bg-red-100 text-red-700" : canvasRun.view.status === "waiting" ? "bg-amber-100 text-amber-800" : "bg-zinc-100 text-zinc-700")}>
                        {canvasRun.view.status ?? "starting"}
                      </span>
                      <span className="flex-1 text-xs text-zinc-500">{running ? "Running on the canvas…" : "Last run"}</span>
                      <StreamToggle />
                      <button type="button" aria-label="Close run" onClick={() => setRunCardOpen(false)} className="text-zinc-400 hover:text-zinc-700 cursor-pointer"><X className="h-3.5 w-3.5" /></button>
                    </div>
                    <div className="max-h-72 space-y-2 overflow-y-auto">
                      {canvasRun.view.approvals.map((a) => <ApprovalCard key={a.id} approval={a} token={token} onDone={() => undefined} />)}
                      {canvasRun.view.output === null && canvasRun.view.live?.text && (
                        <div className="whitespace-pre-wrap text-sm text-zinc-900" aria-live="polite">{canvasRun.view.live.text}<span className="animate-pulse">▍</span></div>
                      )}
                      {canvasRun.view.output !== null && (
                        <>
                          <div className="flex items-center justify-end border-b border-zinc-100 pb-1">
                            <AnswerActions
                              text={canvasRun.view.output}
                              name={doc.name}
                              onExpand={outputNodeId && runNodes[outputNodeId] ? () => ctx.showResult(outputNodeId) : undefined}
                            />
                          </div>
                          <div className="text-sm text-zinc-900"><AnswerView text={canvasRun.view.output} /></div>
                        </>
                      )}
                      {canvasRun.view.status === "failed" && canvasRun.view.error && <p className="text-xs text-red-600">{canvasRun.view.error}</p>}
                      {canvasRun.view.guardrails.map((g, i) => <p key={i} className="text-xs text-amber-700">Guardrail: {g.message}</p>)}
                      {canvasRun.view.sources.length > 0 && <p className="text-xs text-zinc-500">Sources: {canvasRun.view.sources.join(", ")}</p>}
                    </div>
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

        {/* ── the bottom bar: tell AI what to change ── */}
        {canManage && !previewing && (
          <div className="shrink-0 border-t border-zinc-200 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-4">
            <div className="mx-auto max-w-3xl space-y-2">
              {!aiEdit.isPending && !instruction.trim() && (
                <div className="no-scrollbar flex gap-1.5 overflow-x-auto">
                  {CHIPS.map((chip) => (
                    <button key={chip} type="button" onClick={() => setInstruction(chip)} className="shrink-0 rounded-full border border-zinc-200 px-3 py-1 text-xs text-zinc-500 hover:border-zinc-300 hover:bg-zinc-50 hover:text-zinc-900 cursor-pointer">
                      {chip}
                    </button>
                  ))}
                </div>
              )}
              <form
                className="flex items-center gap-1 rounded-xl border border-[var(--border-strong)] bg-[var(--surface)] p-1.5 pl-3 transition focus-within:border-[var(--accent-hover)]"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (instruction.trim() && !aiEdit.isPending) aiEdit.mutate(instruction);
                }}
              >
                <Sparkles className="h-4 w-4 shrink-0 text-zinc-500" />
                <input
                  aria-label="Tell AI what to change"
                  className="min-w-0 flex-1 bg-transparent px-2 py-1.5 text-sm text-zinc-900 outline-none placeholder:text-zinc-500"
                  placeholder="Tell AI what to change in this workflow…"
                  value={instruction}
                  disabled={aiEdit.isPending || improve.isPending}
                  onChange={(e) => setInstruction(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => improve.mutate()}
                  disabled={improve.isPending || aiEdit.isPending || !instruction.trim()}
                  title="Rewrite the instruction more clearly with AI"
                  className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-sm text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-40 cursor-pointer disabled:cursor-default"
                >
                  {improve.isPending ? <Spinner className="h-4 w-4" /> : <Wand2 className="h-4 w-4" />} <span className="hidden sm:inline">Improve</span>
                </button>
                <Button type="submit" size="sm" disabled={aiEdit.isPending || improve.isPending || !instruction.trim()} title="Make this change with AI">
                  {aiEdit.isPending ? <><Spinner className="h-4 w-4" /> Changing…</> : "Change"}
                </Button>
              </form>
            </div>
          </div>
        )}
      </div>
    </CanvasContext.Provider>
  );
}

function Centered({ text, spinner }: { text?: string; spinner?: boolean }) {
  return (
    <div className="builder-dark flex h-full items-center justify-center bg-[var(--bg)] text-sm text-zinc-500">
      {spinner ? <Spinner className="h-6 w-6" /> : text}
    </div>
  );
}

/** One icon button in the editor's toolbar group; the label is its tooltip. */
function IconTool({ label, pressed, disabled, onClick, children }: { label: string; pressed?: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors disabled:opacity-40 cursor-pointer [&_svg]:h-4 [&_svg]:w-4",
        pressed ? "bg-indigo-50 text-indigo-600" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900",
      )}
    >
      {children}
    </button>
  );
}
