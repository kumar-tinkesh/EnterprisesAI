"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, ChevronDown, ChevronRight, Circle, ExternalLink, Paperclip, Plus, SlidersHorizontal, Sparkles, Square, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import { Spinner } from "@/components/ui/spinner";
import { Field, Select } from "@/components/builder/fields";
import { ApprovalCard } from "@/components/builder/approval-card";
import { AnswerMessage, Avatar, AvatarKind, FileChip, GuardrailNotes, UserMessage } from "@/components/builder/chat/chat-message";
import { ChatHistory } from "@/components/builder/chat/chat-history";
import { MarkdownView } from "@/components/builder/chat/markdown-view";
import { coerce } from "@/components/builder/playground";
import { ConnectButton } from "@/components/connections/connect-button";
import { ApiError } from "@/lib/api";
import { builderApi } from "@/lib/builder/api";
import { dayLabel, startersFor } from "@/lib/builder/chat";
import { inputFields, stepTitle } from "@/lib/builder/graph";
import { isFinished, type RunView } from "@/lib/builder/run-state";
import type { Agent, AnswerDepth, Attachment, ChatRef, Problem, Run, Workflow } from "@/lib/builder/types";
import { useRunStream } from "@/lib/builder/use-run-stream";
import { useStreamPref } from "@/lib/builder/stream-pref";
import { cn } from "@/lib/utils";

export type ChatTarget = { kind: "agent" | "workflow"; id: string };

const TONE_DOT = { info: "text-zinc-400", ok: "text-emerald-500", warn: "text-amber-500", error: "text-red-500" } as const;
// What the attach button offers: what the backend can read (builder/api/v1/attachments.py).
export const ACCEPT = ".pdf,.docx,.xlsx,.csv,.md,.txt,.png,.jpg,.jpeg";
export const MAX_FILES = 5;

const DEPTHS: { id: AnswerDepth; label: string; hint: string }[] = [
  { id: "short", label: "Short", hint: "a line or two" },
  { id: "auto", label: "Auto", hint: "sized to the question" },
  { id: "detailed", label: "Detailed", hint: "in depth" },
];

function useElapsed(since: string | null | undefined, running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [running]);
  return since ? Math.max(0, now - new Date(since).getTime()) : 0;
}

/** The turn being answered right now: what it's doing, decisions it waits on, its answer as it lands. */
function LiveAnswer({
  name,
  view,
  since,
  token,
  stepName,
}: {
  name: string;
  view: RunView;
  since: string | null;
  token: string;
  stepName: (nodeId: string) => string;
}) {
  const elapsed = useElapsed(since, true);
  const pending = view.approvals.filter((a) => a.status === "pending");
  const last = view.timeline[view.timeline.length - 1];
  const doing =
    view.status === "waiting"
      ? "Waiting for your decision"
      : view.live?.text
        ? "Writing…"
        : last
        ? `${last.nodeId ? `${stepName(last.nodeId)} ` : ""}${last.text}`
        : view.status === "queued" || view.status === null
          ? "Starting…"
          : "Thinking…";
  return (
    <div className="flex gap-3">
      <Avatar name={name} live />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs text-zinc-500" role="status" aria-live="polite">
          <Spinner className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
          <span className="min-w-0 truncate"><span className="font-medium text-zinc-700">{doing}</span></span>
          <span className="ml-auto shrink-0 tabular-nums text-zinc-500">{(elapsed / 1000).toFixed(1)}s</span>
        </div>
        <GuardrailNotes flags={view.guardrails} />
        {pending.length > 0 && (
          <div className="mt-2 space-y-2">
            {pending.map((a) => (
              <ApprovalCard key={a.id} approval={a} token={token} onDone={() => undefined} />
            ))}
          </div>
        )}
        {view.output ? (
          <div className="mt-2"><MarkdownView text={view.output} /></div>
        ) : view.live?.text ? (
          // The answer as it's being written; the finished one replaces it.
          <div className="mt-2"><MarkdownView text={view.live.text + " ▍"} /></div>
        ) : (
          <div className="mt-2.5 space-y-2" aria-hidden>
            <div className="h-2 w-[80%] animate-pulse rounded-full bg-zinc-100" />
            <div className="h-2 w-[55%] animate-pulse rounded-full bg-zinc-100" />
          </div>
        )}
        {view.timeline.length > 0 && (
          <details className="group/live mt-2">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-zinc-500 hover:text-zinc-900 [&::-webkit-details-marker]:hidden">
              <ChevronRight className="h-3.5 w-3.5 transition-transform group-open/live:rotate-90" /> What it&apos;s doing
              <span>· {view.timeline.length} step{view.timeline.length === 1 ? "" : "s"}</span>
            </summary>
            <ol className="mt-1.5 space-y-1 border-l-2 border-zinc-200 pl-3">
              {view.timeline.map((t) => (
                <li key={t.key} className="flex gap-2 text-xs text-zinc-700">
                  <Circle className={cn("mt-1 h-2 w-2 shrink-0 fill-current", TONE_DOT[t.tone])} />
                  <span className="break-words">
                    {t.nodeId && <span className="font-medium text-zinc-900">{stepName(t.nodeId)} </span>}
                    {t.text}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
    </div>
  );
}

/**
 * Chat with a saved agent or workflow, Marketplace-playground style: the
 * thread, chat history (open, rename, delete), new chats, the live run with
 * its approvals, and why it can't run (with Connect right there). Each
 * message is a real run; an agent remembers the earlier turns of its chat.
 */
export function ChatPanel({
  target,
  token,
  onClose,
  onEdit,
  embedded = false,
}: {
  target: ChatTarget;
  token: string;
  onClose: () => void;
  /** Inside a page that already shows who this is: the header keeps only the chat's own controls. */
  embedded?: boolean;
  /** Open this agent/workflow in the editor beside the chat. */
  onEdit: () => void;
}) {
  const queryClient = useQueryClient();
  const { kind, id } = target;

  const detail = useQuery({
    queryKey: ["builder-chat-target", kind, id],
    queryFn: (): Promise<Agent | Workflow> => (kind === "agent" ? builderApi.getAgent(token, id) : builderApi.getWorkflow(token, id)),
    enabled: !!token,
  });
  const agents = useQuery({ queryKey: ["builder-agents"], queryFn: () => builderApi.listAgents(token), enabled: !!token && kind === "workflow" });
  const name = detail.data?.name || (kind === "agent" ? "Agent" : "Workflow");
  const agentConfig = detail.data && "goal" in detail.data ? detail.data.config : undefined;
  const welcome = agentConfig?.chat?.welcome?.trim();
  const sub = welcome || (detail.data ? ("goal" in detail.data ? detail.data.goal : detail.data.description) : "");
  const starters = startersFor(agentConfig?.chat?.starters);
  // Each person runs an agent as themselves: say up front which of its accounts (or its team's) they still have to connect.
  const needs = useQuery({
    queryKey: ["builder-agent-requirements", id],
    queryFn: () => builderApi.agentRequirements(token, id),
    enabled: !!token && kind === "agent",
  });
  const missing = (needs.data?.requirements ?? []).filter((r) => !r.connected);
  const remembers = !!agentConfig?.memory?.enabled;
  const nodes = useMemo(() => (detail.data && "nodes" in detail.data ? detail.data.nodes : []), [detail.data]);
  const fields = useMemo(() => inputFields(nodes), [nodes]);
  // A workflow's answers can be seen in other formats: its output step, re-run on what reached it.
  const outputNodeId = nodes.find((n) => n.type === "output")?.id;
  const reshape = useMemo(
    () => (kind === "workflow" && outputNodeId ? { token, workflowId: id, nodeId: outputNodeId } : undefined),
    [kind, outputNodeId, token, id],
  );
  const stepName = useCallback(
    (nodeId: string) => {
      const byId: Record<string, Agent> = Object.fromEntries((agents.data ?? []).map((a) => [a.id, a]));
      const node = nodes.find((n) => n.id === nodeId);
      return node ? stepTitle(node, byId) : nodeId === "agent" ? name : nodeId;
    },
    [nodes, agents.data, name],
  );

  // ── Chats ──
  const chatsKey = ["builder-chats", kind, id];
  const chats = useQuery({
    queryKey: chatsKey,
    queryFn: () => builderApi.listConversations(token, kind === "agent" ? { agent_id: id } : { workflow_id: id }),
    enabled: !!token,
  });
  // undefined = not chosen yet (the latest chat once the list loads); null = a new, empty chat.
  const [picked, setPicked] = useState<string | null | undefined>(undefined);
  const chatId = picked === undefined ? (chats.data?.[0]?.id ?? null) : picked;
  const chat = chats.data?.find((c) => c.id === chatId) ?? null;

  const runs = useQuery({
    queryKey: ["builder-chat-runs", chatId],
    queryFn: () => builderApi.conversationRuns(token, chatId!),
    enabled: !!token && !!chatId,
  });
  const thread: Run[] = useMemo(() => (chatId ? (runs.data ?? []) : []), [chatId, runs.data]);

  // ── The run being answered now ──
  const [liveRunId, setLiveRunId] = useState<string | null>(null);
  const [pendingText, setPendingText] = useState<string | null>(null);
  const { view } = useRunStream(liveRunId, token);
  const liveRun = thread.find((r) => r.id === liveRunId);

  // Reopened while a run is still going (or a chat switched to one): follow it.
  useEffect(() => {
    const last = thread[thread.length - 1];
    if (!liveRunId && last && !isFinished(last.status)) setLiveRunId(last.id);
  }, [thread, liveRunId]);

  // Finished: fetch the full run (tool calls, timings) into the thread, then stop following it.
  useEffect(() => {
    if (!liveRunId || !isFinished(view.status) || view.runId !== liveRunId) return;
    let stale = false;
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["builder-chat-runs", chatId] }),
      queryClient.invalidateQueries({ queryKey: chatsKey }),
    ]).then(() => !stale && setLiveRunId(null));
    return () => {
      stale = true;
    };
  }, [liveRunId, view.status, view.runId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sending ──
  const [input, setInput] = useState("");
  const [depth, setDepth] = useState<AnswerDepth>("auto");
  const [streamOn, setStreamOn] = useStreamPref();
  const [values, setValues] = useState<Record<string, string>>({});
  const [showInputs, setShowInputs] = useState(false);
  const [problems, setProblems] = useState<Problem[]>([]);
  const missingRequired = fields.filter((f) => f.required && !(values[f.name] ?? "").trim());
  const inputsOpen = showInputs || missingRequired.length > 0;

  // ── Files for the next message (agents only) ──
  const [files, setFiles] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(0);
  const [fileError, setFileError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const attach = async (list: FileList | null) => {
    setFileError(null);
    const chosen = Array.from(list ?? []).slice(0, Math.max(0, MAX_FILES - files.length));
    if ((list?.length ?? 0) > chosen.length) setFileError(`At most ${MAX_FILES} files per message.`);
    for (const file of chosen) {
      setUploading((n) => n + 1);
      try {
        const uploaded = await builderApi.uploadAttachment(token, file);
        setFiles((cur) => [...cur, uploaded]);
      } catch (err) {
        setFileError(err instanceof Error ? `${file.name}: ${err.message}` : `Couldn't attach ${file.name}.`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  };

  const send = useMutation({
    mutationFn: async (text: string): Promise<Run> => {
      setProblems([]);
      const ref: ChatRef = chatId ? { conversation_id: chatId } : { new_conversation: true };
      if (kind === "agent") return builderApi.startAgentRun(token, id, text, depth, ref, files.map((f) => f.id), streamOn);
      const variables: Record<string, unknown> = {};
      for (const f of fields) {
        const v = coerce(f, values[f.name] ?? "");
        if (v !== undefined) variables[f.name] = v;
      }
      return builderApi.startWorkflowRun(token, id, text, variables, depth, ref, streamOn, files.map((f) => f.id));
    },
    onMutate: (text) => setPendingText(text),
    onSuccess: async (run) => {
      setFiles([]);
      setLiveRunId(run.id);
      if (run.conversation_id && run.conversation_id !== chatId) setPicked(run.conversation_id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: chatsKey }),
        queryClient.invalidateQueries({ queryKey: ["builder-chat-runs", run.conversation_id ?? chatId] }),
      ]);
      setPendingText(null);
    },
    onError: (err, text) => {
      setPendingText(null);
      setInput((cur) => cur || text);
      const list = err instanceof ApiError ? ((err.body as { problems?: Problem[] })?.problems ?? []) : [];
      setProblems(list.length ? list : [{ code: "error", message: err instanceof Error ? err.message : "Couldn't send that." }]);
      if (list.some((p) => p.code === "missing_input" || p.code === "missing_variable")) setShowInputs(true);
    },
  });
  const stop = useMutation({ mutationFn: () => builderApi.cancelRun(token, liveRunId!) });

  const busy = send.isPending || (!!liveRunId && !isFinished(view.status));
  const canSend = !busy && uploading === 0 && !!token && (input.trim().length > 0 || (kind === "workflow" && (fields.length > 0 || files.length > 0))) && missingRequired.length === 0;
  const submit = (text = input) => {
    if (busy || uploading > 0 || (!text.trim() && kind === "agent")) return;
    if (missingRequired.length) {
      setShowInputs(true);
      return;
    }
    setInput("");
    send.mutate(text.trim());
  };

  const newChat = () => {
    setPicked(null);
    setLiveRunId(null);
    setProblems([]);
    composer.current?.focus();
  };
  const openChat = (cid: string) => {
    setPicked(cid);
    setLiveRunId(null);
    setProblems([]);
  };
  const removeChat = async (cid: string) => {
    await builderApi.deleteConversation(token, cid);
    if (cid === chatId) newChat();
    queryClient.setQueryData(chatsKey, (list: typeof chats.data) => (list ?? []).filter((c) => c.id !== cid));
    queryClient.removeQueries({ queryKey: ["builder-chat-runs", cid] });
  };
  const renameChat = async (cid: string, title: string) => {
    const updated = await builderApi.renameConversation(token, cid, title);
    queryClient.setQueryData(chatsKey, (list: typeof chats.data) => (list ?? []).map((c) => (c.id === cid ? updated : c)));
  };

  // ── Scrolling ──
  const scroller = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  useEffect(() => {
    if (atBottom) end.current?.scrollIntoView({ block: "end" });
  }, [thread.length, pendingText, view.timeline.length, view.output, view.live?.text, view.approvals.length, atBottom]);
  useEffect(() => {
    setAtBottom(true);
  }, [chatId]);

  // Composer grows with its text.
  useLayoutEffect(() => {
    const el = composer.current;
    if (!el) return;
    el.style.height = "auto";
    // Empty: one line, even when a long placeholder would wrap.
    el.style.height = input ? `${Math.min(el.scrollHeight, 160)}px` : "36px";
  }, [input]);

  const empty = !chatId ? !pendingText : thread.length === 0 && !pendingText && !runs.isLoading;
  const editorTitle = kind === "agent" ? "Open in the agent editor" : "Open in the workflow editor";

  return (
    <AvatarKind.Provider value={kind}>
    <div className="flex h-full min-h-0 flex-col bg-[var(--bg)]">
      {/* Header */}
      <header className="flex shrink-0 items-center gap-2 border-b border-zinc-200 px-3 py-2 sm:px-4">
        {!embedded && <Avatar name={name} size={32} />}
        <div className="min-w-0 flex-1">
          {!embedded && <p className="truncate text-sm font-semibold text-zinc-900">{name}</p>}
          <p className={cn("truncate", embedded ? "text-sm font-medium text-zinc-900" : "text-xs text-zinc-500")}>{chat ? chat.title : "New chat"}</p>
        </div>
        <button
          type="button"
          onClick={newChat}
          aria-label="New chat"
          title="New chat — this one stays in your history"
          className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"
        >
          <Plus className="h-4 w-4" /> <span className="hidden sm:inline">New chat</span>
        </button>
        <ChatHistory
          chats={chats.data ?? []}
          loading={chats.isLoading}
          currentId={chatId}
          onOpen={openChat}
          onNew={newChat}
          onRename={renameChat}
          onDelete={removeChat}
        />
        {!embedded && (
          <>
            <button
              type="button"
              onClick={onEdit}
              aria-label={editorTitle}
              title={editorTitle}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"
            >
              <ExternalLink className="h-4 w-4" />
            </button>
            <button type="button" onClick={onClose} aria-label="Close chat" className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer">
              <X className="h-4 w-4" />
            </button>
          </>
        )}
      </header>

      {/* Thread */}
      <div className="relative min-h-0 flex-1">
        <div
          ref={scroller}
          onScroll={(e) => {
            const el = e.currentTarget;
            setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
          }}
          className="absolute inset-0 overflow-y-auto overscroll-contain px-4 py-6 sm:px-6"
        >
          <div className="mx-auto flex max-w-[720px] flex-col gap-8">
            {chatId && runs.isLoading && <div className="flex justify-center py-8"><Spinner className="h-5 w-5 text-zinc-400" /></div>}
            {runs.isError && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">Couldn&apos;t load this chat.</p>}

            {empty && (
              <div className="mx-auto flex max-w-lg flex-col items-center py-10 text-center">
                <Avatar name={name} size={56} />
                <h2 className="mt-4 text-xl font-semibold text-zinc-900">{name}</h2>
                {sub && <p className={cn("mt-1.5 line-clamp-3", welcome ? "text-sm text-zinc-700" : "text-sm text-zinc-500")}>{sub}</p>}
                <p className="mt-2 text-xs text-zinc-500">
                  Runs with your connected accounts.{" "}
                  {kind === "agent"
                    ? remembers
                      ? "It remembers this chat, and what it has learned about you across chats."
                      : "It remembers the earlier messages of this chat."
                    : `Each message runs the workflow, start to finish.${fields.length > 0 ? " Fill in its inputs above the message box." : ""}`}
                </p>
                {missing.length > 0 && (
                  <div className="mt-4 w-full space-y-1.5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-left">
                    <p className="text-sm font-medium text-zinc-900">Connect your account{missing.length === 1 ? "" : "s"} first</p>
                    {missing.map((r) => (
                      <div key={r.server_id} className="flex items-center gap-2 text-sm text-zinc-700">
                        <span className="min-w-0 flex-1 truncate" title={r.tools.join(", ")}>
                          {r.name} <span className="text-zinc-500">· for {r.tools.length} tool{r.tools.length === 1 ? "" : "s"}</span>
                        </span>
                        <ConnectButton
                          serverId={r.server_id}
                          serverName={r.name}
                          token={token}
                          onConnected={() => void queryClient.invalidateQueries({ queryKey: ["builder-agent-requirements", id] })}
                        />
                      </div>
                    ))}
                  </div>
                )}
                {kind === "agent" && (
                  <ul className={cn("mt-6 grid w-full gap-2", starters.length === 4 ? "sm:grid-cols-2" : "sm:grid-cols-3")}>
                    {starters.map((s) => (
                      <li key={s.label}>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => submit(s.prompt)}
                          className="group flex h-full w-full items-center justify-between gap-2 rounded-lg border border-zinc-200 p-3 text-left text-sm text-zinc-700 transition-colors hover:border-zinc-300 hover:bg-zinc-50 hover:text-zinc-900 disabled:opacity-50 cursor-pointer"
                        >
                          <span className="flex items-center gap-2"><Sparkles className="h-4 w-4 shrink-0 text-zinc-400" /> {s.label}</span>
                          <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400 group-hover:text-zinc-900" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {thread.map((run, i) => {
              const prev = thread[i - 1];
              const showDay = !prev || new Date(prev.created_at).toDateString() !== new Date(run.created_at).toDateString();
              const following = run.id === liveRunId && !isFinished(view.runId === run.id ? view.status : run.status);
              return (
                <div key={run.id} className="flex flex-col gap-4">
                  {showDay && (
                    <p className="text-center text-xs text-zinc-500" aria-hidden>{dayLabel(run.created_at)}</p>
                  )}
                  <UserMessage
                    files={run.input?.attachments}
                    text={run.input?.text || (kind === "workflow" ? "(ran with its inputs)" : "")}
                    onEdit={run.input?.text ? () => {
                      setInput(run.input.text);
                      composer.current?.focus();
                    } : undefined}
                  />
                  {following ? (
                    <LiveAnswer name={name} view={view} since={run.started_at ?? run.created_at} token={token} stepName={stepName} />
                  ) : (
                    <AnswerMessage
                      run={run}
                      name={name}
                      latest={i === thread.length - 1}
                      retryDisabled={busy}
                      onRetry={() => submit(run.input?.text ?? "")}
                      stepName={stepName}
                      reshape={reshape}
                    />
                  )}
                </div>
              );
            })}

            {pendingText !== null && !liveRun && (
              <div className="flex flex-col gap-4">
                <UserMessage text={pendingText || "(ran with its inputs)"} files={files} />
                <LiveAnswer name={name} view={{ ...view, timeline: [], approvals: [], output: null, guardrails: [], status: null }} since={null} token={token} stepName={stepName} />
              </div>
            )}
            <div ref={end} />
          </div>
        </div>
        {!atBottom && (
          <button
            type="button"
            onClick={() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" })}
            className="absolute bottom-3 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-zinc-200 bg-[var(--surface-raised)] px-3 py-1.5 text-xs font-medium text-zinc-700 shadow-lg hover:text-zinc-900 cursor-pointer"
          >
            <ArrowDown className="h-3 w-3" /> Jump to latest
          </button>
        )}
      </div>

      {/* Composer */}
      <div className="shrink-0 px-3 pb-3 pt-2 sm:px-4 sm:pb-4">
        <div className="mx-auto max-w-[720px] space-y-2">
          {problems.length > 0 && (
            <div className="space-y-1.5 rounded-lg border border-red-200 bg-red-50 p-3" role="alert">
              <p className="text-sm font-medium text-zinc-900">It can&apos;t run yet</p>
              {problems.map((p, i) => (
                <p key={i} className="flex flex-wrap items-center gap-1.5 text-sm text-red-700">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1">{p.message}</span>
                  {p.code === "not_connected" && p.server_id && (
                    <ConnectButton
                      serverId={p.server_id}
                      token={token}
                      onConnected={() => setProblems((list) => list.filter((x) => !(x.code === "not_connected" && x.server_id === p.server_id)))}
                    />
                  )}
                </p>
              ))}
            </div>
          )}

          {/* A workflow's inputs: a small form card over the message box, open while any required one is empty. */}
          {kind === "workflow" && fields.length > 0 && (
            <div className="rounded-xl border border-zinc-200 bg-[var(--surface)]">
              <button
                type="button"
                onClick={() => setShowInputs((s) => !s)}
                aria-expanded={inputsOpen}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-sm font-medium text-zinc-900 cursor-pointer"
              >
                <SlidersHorizontal className="h-4 w-4 text-zinc-500" /> Inputs
                <span className={cn("text-xs font-normal", missingRequired.length ? "text-amber-700" : "text-zinc-500")}>
                  {missingRequired.length ? `${missingRequired.length} required` : `${fields.length} filled in`}
                </span>
                <ChevronDown className={cn("ml-auto h-4 w-4 text-zinc-500 transition-transform", inputsOpen && "rotate-180")} />
              </button>
              {inputsOpen && (
                <div className="grid gap-3 border-t border-zinc-200 p-3 sm:grid-cols-2">
                  {fields.map((f) => (
                    <Field key={f.name} label={`${f.label || f.name}${f.required ? " *" : ""}`} hint={f.type === "boolean" ? undefined : f.description ?? undefined}>
                      {f.type === "boolean" ? (
                        <Select value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                          <option value="">—</option>
                          <option value="true">Yes</option>
                          <option value="false">No</option>
                        </Select>
                      ) : (
                        <Input
                          type={f.type === "number" ? "number" : "text"}
                          value={values[f.name] ?? ""}
                          onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                        />
                      )}
                    </Field>
                  ))}
                </div>
              )}
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="rounded-2xl border border-[var(--border-strong)] bg-[var(--surface)] px-3 pb-2 pt-3 transition focus-within:border-[var(--accent-hover)]"
          >
            {(files.length > 0 || uploading > 0 || fileError) && (
              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                {files.map((f) => (
                  <FileChip key={f.id} file={f} onRemove={() => setFiles((cur) => cur.filter((x) => x.id !== f.id))} />
                ))}
                {uploading > 0 && <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500"><Spinner className="h-3 w-3" /> Reading {uploading} file{uploading === 1 ? "" : "s"}…</span>}
                {fileError && <span className="text-xs text-red-600">{fileError}</span>}
              </div>
            )}
            <textarea
              ref={composer}
              rows={1}
              value={input}
              aria-label={`Message ${name}`}
              placeholder={kind === "agent" ? `Ask ${name} anything…` : `What should ${name} work on?`}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              className="block max-h-40 min-h-[36px] w-full resize-none bg-transparent px-1 py-1 text-sm text-zinc-900 outline-none placeholder:text-zinc-500"
            />
            <div className="mt-1 flex items-center gap-1">
              <input
                ref={picker}
                type="file"
                multiple
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => {
                  void attach(e.target.files);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => picker.current?.click()}
                disabled={busy || files.length >= MAX_FILES}
                aria-label="Attach files"
                title="Attach a document (PDF, Word, Excel, CSV, text) or an image (JPG, PNG)"
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 disabled:opacity-40 cursor-pointer"
              >
                <Paperclip className="h-4 w-4" />
              </button>
              <Menu
                label="Answer settings"
                trigger={<>Length: {DEPTHS.find((d) => d.id === depth)?.label} <ChevronDown className="h-3.5 w-3.5" /></>}
                triggerClassName="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs font-medium text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer"
                items={[
                  ...DEPTHS.map((d) => ({ label: `${d.label} — ${d.hint}`, checked: depth === d.id, onClick: () => setDepth(d.id) })),
                  { label: "Show the answer as it's written", checked: streamOn, divided: true, onClick: () => setStreamOn(!streamOn) },
                ]}
              />
              {busy && liveRunId ? (
                <button
                  type="button"
                  onClick={() => stop.mutate()}
                  disabled={stop.isPending}
                  aria-label="Stop"
                  title="Stop"
                  className="ml-auto inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-[var(--bg)] hover:opacity-90 disabled:opacity-50 cursor-pointer"
                >
                  <Square className="h-3 w-3 fill-current" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!canSend}
                  aria-label="Send"
                  title="Send (Enter) · new line: Shift+Enter"
                  className="ml-auto inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:bg-zinc-200 disabled:text-zinc-500 cursor-pointer disabled:cursor-default"
                >
                  {send.isPending ? <Spinner className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
                </button>
              )}
            </div>
          </form>
        </div>
      </div>
    </div>
    </AvatarKind.Provider>
  );
}
