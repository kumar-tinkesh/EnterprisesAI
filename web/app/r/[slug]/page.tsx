"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Check, ChevronRight, Circle, History, Info, LogIn, RotateCw, ShieldAlert, Square, UserPlus, X, XCircle } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import { Spinner } from "@/components/ui/spinner";
import { Field, Select } from "@/components/builder/fields";
import { ApprovalCard } from "@/components/builder/approval-card";
import { CopyButton } from "@/components/builder/chat/chat-message";
import { MarkdownView } from "@/components/builder/chat/markdown-view";
import { AnswerView } from "@/components/builder/run-output";
import { NeedsList } from "@/components/builder/tool-needs";
import { TypeIcon } from "@/components/builder/type-icon";
import { ApiError } from "@/lib/api";
import { sharedApi } from "@/lib/builder/api";
import { formatCost, formatDuration, formatTokens } from "@/lib/builder/chat";
import type { InputVariable, SharedInfo, SharedNeeds, SharedRun, SharedStep, ToolMode } from "@/lib/builder/types";
import { useStreamPref } from "@/lib/builder/stream-pref";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const DONE = new Set(["succeeded", "failed", "cancelled"]);

function ago(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** Read a Server-Sent Events body: ``on(event, data)`` per message, until it ends. */
async function readEvents(res: Response, on: (event: string, data: unknown) => void): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) on(event, JSON.parse(data));
    }
  }
}

/** The answer being written: one turn's text, built from batches that must line up (``at``). */
type Live = { runId: string; turn: number; text: string };

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const problems = (err.body as { problems?: string[] })?.problems ?? [];
    return problems.length ? `${err.message} ${problems.join(" ")}` : err.message;
  }
  return "Couldn't reach the server. Try again.";
}

/** Whose accounts it runs with, in one sentence (the details live under How it works). */
function accountsNote(mode: ToolMode): string {
  if (mode === "publisher") return "It runs with the sharer's accounts; anything that would change data waits for their OK.";
  if (mode === "mixed") return "It runs as you, with your accounts — except a few apps that stay the sharer's. It asks before changing anything.";
  return "It runs as you, with your own accounts, and asks you before it changes anything. Whoever shared it sees that you used it, not what was in it.";
}

type Panel = "outline" | "history" | null;

/**
 * A share link (/r/{slug}): one page to ask it something and read the answer,
 * like a chat. "How it works" (when the sharer shows it) and your earlier runs
 * open beside it. On a "publisher" link runs use the sharer's tools, so
 * anything that would change data waits for THEIR approval — this page shows
 * that wait. On a "visitor" link they use the person's own: they connect what's
 * missing here first, and decide their own approvals here too. A "mixed" link
 * is a visitor one where some apps are the sharer's — their account, their OK.
 */
export default function SharedPage() {
  const { slug } = useParams<{ slug: string }>();
  const token = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  // The saved sign-in is only readable after the first client render.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const [panel, setPanel] = useState<Panel>(null);

  const info = useQuery({ queryKey: ["shared-info", slug], queryFn: () => sharedApi.info(slug), retry: false });
  const authHref = (mode: "login" | "signup") => `/auth?next=${encodeURIComponent(`/r/${slug}`)}${mode === "signup" ? "&mode=signup" : ""}`;
  const signedIn = mounted && !!token && !!user;

  if (info.isLoading) return <div className="flex min-h-dvh items-center justify-center bg-[var(--bg)]"><Spinner className="h-6 w-6 text-zinc-400" /></div>;
  if (info.isError || !info.data) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-[var(--bg)] p-4">
        <div className="max-w-sm text-center">
          <p className="text-base font-semibold text-zinc-900">{info.error instanceof ApiError ? info.error.message : "This link couldn't be opened."}</p>
          <p className="mt-1 text-sm text-zinc-500">Ask whoever sent it for a new one.</p>
        </div>
      </main>
    );
  }
  const shared = info.data;

  return (
    <div className="flex h-dvh flex-col bg-[var(--bg)]">
      <header className="flex shrink-0 items-center gap-2 border-b border-zinc-200 px-3 py-2 sm:px-4">
        <TypeIcon kind={shared.kind} size="sm" />
        <h1 className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-900">{shared.name}</h1>
        {shared.show_outline && (
          <HeaderButton on={panel === "outline"} onClick={() => setPanel(panel === "outline" ? null : "outline")} label="How it works">
            <Info className="h-4 w-4" />
          </HeaderButton>
        )}
        {signedIn && (
          <HeaderButton on={panel === "history"} onClick={() => setPanel(panel === "history" ? null : "history")} label="History">
            <History className="h-4 w-4" />
          </HeaderButton>
        )}
        {signedIn ? (
          <Menu
            label="Account"
            trigger={<span className="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-100 text-xs font-semibold text-zinc-700">{(user!.full_name || user!.email).slice(0, 1).toUpperCase()}</span>}
            triggerClassName="shrink-0 rounded-full p-0.5 hover:bg-zinc-100 cursor-pointer"
            items={[{ label: `Sign out (${user!.email})`, onClick: logout }]}
          />
        ) : mounted ? (
          <Link href={authHref("login")} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "shrink-0")}><LogIn /> Log in</Link>
        ) : null}
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1">
          {!mounted ? null : signedIn ? (
            <Runner slug={slug} token={token!} shared={shared} panel={panel} setPanel={setPanel} />
          ) : (
            <div className="h-full overflow-y-auto px-4 py-10">
              <div className="mx-auto max-w-[720px]">
                <Intro shared={shared} />
                <div className="mx-auto mt-8 max-w-sm rounded-xl border border-zinc-200 p-5 text-center">
                  <p className="text-base font-semibold text-zinc-900">Sign in to use it</p>
                  <p className="mt-1 text-sm text-zinc-500">It&apos;s free. You&apos;ll come straight back here.</p>
                  <div className="mt-4 flex justify-center gap-2">
                    <Link href={authHref("login")} className={buttonVariants({ variant: "outline" })}><LogIn /> Log in</Link>
                    <Link href={authHref("signup")} className={buttonVariants()}><UserPlus /> Sign up</Link>
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
        {panel === "outline" && shared.show_outline && (
          <Drawer title="How it works" onClose={() => setPanel(null)}>
            <Outline slug={slug} mode={shared.tool_mode} />
          </Drawer>
        )}
      </div>
    </div>
  );
}

function HeaderButton({ on, onClick, label, children }: { on: boolean; onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label={label}
      title={label}
      className={cn("inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2 text-sm transition-colors cursor-pointer sm:px-2.5", on ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900")}
    >
      {children} <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

/** A side panel: beside the page from md, over it on a phone. */
function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <aside className="fixed inset-0 z-40 flex flex-col bg-[var(--surface)] md:static md:z-auto md:w-96 md:shrink-0 md:border-l md:border-zinc-200" aria-label={title}>
      <div className="flex shrink-0 items-center justify-between px-4 py-3">
        <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-6">{children}</div>
    </aside>
  );
}

/** What it is: shown until the first answer. */
function Intro({ shared }: { shared: SharedInfo }) {
  return (
    <div className="flex flex-col items-center text-center">
      <TypeIcon kind={shared.kind} size="lg" />
      <h2 className="mt-4 text-xl font-semibold text-zinc-900">{shared.name}</h2>
      {shared.description && <p className="mt-1.5 line-clamp-4 max-w-lg text-sm text-zinc-500">{shared.description}</p>}
      {shared.shared_by && <p className="mt-2 text-xs text-zinc-500">Shared by {shared.shared_by}</p>}
    </div>
  );
}

/** The steps and their apps, read-only — the sharer's instructions are never part of it. */
function Outline({ slug, mode }: { slug: string; mode: ToolMode }) {
  const outline = useQuery({ queryKey: ["shared-outline", slug], queryFn: () => sharedApi.outline(slug), retry: false });
  if (outline.isLoading) return <Spinner className="h-5 w-5 text-zinc-400" />;
  if (outline.isError || !outline.data) return <p className="text-sm text-zinc-500">{outline.error instanceof ApiError ? outline.error.message : "Couldn't load it."}</p>;
  const levels = [...new Set(outline.data.steps.map((s) => s.level))].sort((a, b) => a - b);
  let n = 0;
  return (
    <div className="space-y-5">
      <ol className="space-y-3">
        {levels.map((level) => {
          const steps = outline.data!.steps.filter((s) => s.level === level);
          return (
            <li key={level} className="space-y-2">
              {steps.length > 1 && <p className="text-xs text-zinc-500">These {steps.length} run side by side</p>}
              {steps.map((s) => {
                n += 1;
                return (
                  <div key={s.id} className="flex gap-3 rounded-lg border border-zinc-200 p-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-medium text-zinc-700">{n}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-zinc-900">{s.title}</p>
                      {s.hint && <p className="mt-0.5 text-xs text-zinc-500">{s.hint}</p>}
                      {s.apps.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {s.apps.map((a) => <span key={a} className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-700">{a}</span>)}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </li>
          );
        })}
      </ol>
      <div className="space-y-1.5 border-t border-zinc-200 pt-4 text-xs text-zinc-500">
        <p>{accountsNote(mode)}</p>
        {outline.data.asks_before_changes && <p>Steps that would change data ask for approval first.</p>}
      </div>
    </div>
  );
}

function Runner({
  slug, token, shared, panel, setPanel,
}: { slug: string; token: string; shared: SharedInfo; panel: Panel; setPanel: (p: Panel) => void }) {
  const { inputs, kind, tool_mode: toolMode, per_user_daily_limit: limit } = shared;
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState<SharedRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [streamOn] = useStreamPref();
  const alive = useRef(true);
  const watching = useRef<AbortController | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => () => {
    alive.current = false;
    watching.current?.abort();
  }, []);

  const history = useQuery({ queryKey: ["shared-runs", slug, token], queryFn: () => sharedApi.runs(token, slug) });
  const own = toolMode !== "publisher";
  // Under "builder-tool-needs": connecting an account anywhere refreshes it (server-connect invalidates that key).
  const needs = useQuery({ queryKey: ["builder-tool-needs", "shared", slug, token], queryFn: () => sharedApi.needs(token, slug), enabled: own });
  const refreshHistory = useCallback(() => void queryClient.invalidateQueries({ queryKey: ["shared-runs", slug] }), [queryClient, slug]);

  // Follow a run until it's done. A run waiting on the sharer's approval keeps
  // being checked, just less often: they may decide while this page is open.
  const follow = useCallback(async (run: SharedRun) => {
    let r = run;
    while (alive.current && !DONE.has(r.status)) {
      await new Promise((ok) => setTimeout(ok, r.status === "waiting" ? 5000 : 2000));
      if (!alive.current) return;
      try {
        r = await sharedApi.get(token, slug, r.run_id);
      } catch {
        continue;
      }
      setCurrent((c) => (c?.run_id === r.run_id ? r : c));
    }
    refreshHistory();
  }, [token, slug, refreshHistory]);

  // Watch a run live: its state and the answer as it's written. Falls back to
  // checking every few seconds if the live connection can't be had or drops.
  const watch = useCallback(async (run: SharedRun) => {
    watching.current?.abort();
    const ctrl = new AbortController();
    watching.current = ctrl;
    let last = run;
    try {
      const res = await sharedApi.events(token, slug, run.run_id, ctrl.signal);
      if (!res.ok || !res.body) throw new Error(String(res.status));
      await readEvents(res, (event, data) => {
        if (event === "run") {
          last = data as SharedRun;
          setCurrent((c) => (c?.run_id === last.run_id ? last : c));
          if (last.output !== null || DONE.has(last.status)) setLive((l) => (l?.runId === last.run_id ? null : l));
        } else if (event === "delta") {
          const d = data as { turn: number; at: number; text: string };
          setLive((l) =>
            d.at === 0 ? { runId: run.run_id, turn: d.turn, text: d.text }
              : l && l.runId === run.run_id && l.turn === d.turn && l.text.length === d.at ? { ...l, text: l.text + d.text }
                : l,
          );
        }
      });
    } catch {
      if (ctrl.signal.aborted) return;
    }
    if (ctrl.signal.aborted || !alive.current) return;
    if (DONE.has(last.status)) refreshHistory();
    else void follow(last);
  }, [token, slug, follow, refreshHistory]);

  const variables = () => {
    const out: Record<string, unknown> = {};
    for (const v of inputs) {
      const raw = (values[v.name] ?? "").trim();
      if (!raw) continue;
      if (v.type === "number") out[v.name] = Number(raw);
      else if (v.type === "boolean") out[v.name] = raw === "true";
      else if (v.type === "json") {
        try { out[v.name] = JSON.parse(raw); } catch { out[v.name] = raw; }
      } else out[v.name] = raw;
    }
    return out;
  };

  const submit = async (input = text) => {
    setBusy(true);
    setError(null);
    try {
      // Streaming: start at once and watch it being written; otherwise wait a little for the whole answer.
      const run = await sharedApi.run(token, slug, { input: input.trim(), variables: variables(), wait_seconds: streamOn ? 0 : 20, stream: streamOn });
      setCurrent(run);
      setLive(null);
      setText("");
      refreshHistory();
      if (!DONE.has(run.status)) void (streamOn ? watch(run) : follow(run));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const open = (run: SharedRun) => {
    setCurrent(run);
    setLive(null);
    if (!DONE.has(run.status)) void (streamOn ? watch(run) : follow(run));
  };

  const [stopping, setStopping] = useState(false);
  const stop = async () => {
    if (!current) return;
    setStopping(true);
    try {
      setCurrent(await sharedApi.cancel(token, slug, current.run_id));
    } catch {
      /* it may have just finished */
    } finally {
      setStopping(false);
    }
  };

  // The box grows with what's typed.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = text ? `${Math.min(el.scrollHeight, 160)}px` : "36px";
  }, [text]);

  const missing = inputs.filter((v) => v.required && !(values[v.name] ?? "").trim());
  const blocked = own && (!needs.data || needs.data.problems.length > 0);
  const running = !!current && !DONE.has(current.status);
  const canSend = !busy && !running && missing.length === 0 && !blocked && (kind === "workflow" || !!text.trim());

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-8">
          <div className="mx-auto max-w-[720px] space-y-8">
            {!current && (
              <>
                <Intro shared={shared} />
                <Accounts own={own} mode={toolMode} needs={needs.data} loading={needs.isLoading} error={needs.isError ? errorText(needs.error) : null} token={token} />
              </>
            )}
            {current && (
              <Turn
                run={current}
                live={live?.runId === current.run_id ? live.text : ""}
                kind={kind}
                own={own}
                token={token}
                onRetry={!busy && !running && !blocked && missing.length === 0 ? () => void submit(current.input) : undefined}
                onDecided={async () => {
                  try {
                    setCurrent(await sharedApi.get(token, slug, current.run_id));
                  } catch {
                    /* the poll picks it up */
                  }
                }}
              />
            )}
          </div>
        </div>

        <div className="shrink-0 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-4">
          <div className="mx-auto max-w-[720px] space-y-2">
            {current && own && blocked && needs.data && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-sm text-zinc-700">{needs.data.problems.join(" ")}</p>
            )}
            {inputs.length > 0 && (
              <div className="grid gap-3 rounded-xl border border-zinc-200 bg-[var(--surface)] p-3 sm:grid-cols-2">
                {inputs.map((v) => <InputField key={v.name} v={v} value={values[v.name] ?? ""} onChange={(x) => setValues({ ...values, [v.name]: x })} />)}
              </div>
            )}
            {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (canSend) void submit();
              }}
              className="rounded-2xl border border-[var(--border-strong)] bg-[var(--surface)] px-3 pb-2 pt-2.5 transition focus-within:border-[var(--accent-hover)]"
            >
              <textarea
                ref={box}
                rows={1}
                value={text}
                maxLength={8000}
                aria-label={kind === "agent" ? "Your question" : "Your request"}
                placeholder={kind === "agent" ? "Ask anything…" : inputs.length ? "Anything to add? (optional)" : "What should it work on?"}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    if (canSend) void submit();
                  }
                }}
                className="block max-h-40 min-h-[36px] w-full resize-none bg-transparent px-1 py-1 text-sm text-zinc-900 outline-none placeholder:text-zinc-500"
              />
              <div className="mt-1 flex items-center gap-2">
                <p className="min-w-0 flex-1 truncate text-xs text-zinc-500">
                  {missing.length ? `Fill in ${missing.map((v) => v.label || v.name).join(", ")} first.` : limit ? `Up to ${limit} runs a day.` : ""}
                </p>
                {running ? (
                  <button
                    type="button"
                    onClick={() => void stop()}
                    disabled={stopping}
                    aria-label="Stop"
                    title="Stop"
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-[var(--bg)] hover:opacity-90 disabled:opacity-50 cursor-pointer"
                  >
                    {stopping ? <Spinner className="h-4 w-4" /> : <Square className="h-3 w-3 fill-current" />}
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!canSend}
                    aria-label="Send"
                    title="Send (Enter) · new line: Shift+Enter"
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:bg-zinc-200 disabled:text-zinc-500 cursor-pointer disabled:cursor-default"
                  >
                    {busy ? <Spinner className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      </div>

      {panel === "history" && (
        <Drawer title="Your runs" onClose={() => setPanel(null)}>
          {history.isLoading ? (
            <Spinner className="h-5 w-5 text-zinc-400" />
          ) : (history.data ?? []).length === 0 ? (
            <p className="text-sm text-zinc-500">Nothing yet. Your questions and answers will be listed here.</p>
          ) : (
            <ul className="-mx-2 space-y-0.5">
              <li>
                <button
                  type="button"
                  onClick={() => {
                    setCurrent(null);
                    setLive(null);
                    setPanel(null);
                    box.current?.focus();
                  }}
                  className="w-full rounded-md px-2 py-2 text-left text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:text-zinc-900 cursor-pointer"
                >
                  + Ask something new
                </button>
              </li>
              {history.data!.map((r) => (
                <li key={r.run_id}>
                  <button
                    type="button"
                    onClick={() => {
                      open(r);
                      if (window.matchMedia("(max-width: 767px)").matches) setPanel(null);
                    }}
                    className={cn("flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-zinc-50 cursor-pointer", current?.run_id === r.run_id && "bg-zinc-100")}
                  >
                    <StatusDot run={r} />
                    <span className="min-w-0 flex-1 truncate text-sm text-zinc-900">{r.input || "(ran with its inputs)"}</span>
                    <span className="shrink-0 text-xs text-zinc-500">{ago(r.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Drawer>
      )}
    </div>
  );
}

/** The accounts it needs, as one line of chips; only what's missing asks for anything. */
function Accounts({
  own, mode, needs, loading, error, token,
}: {
  own: boolean;
  mode: ToolMode;
  needs: SharedNeeds | undefined;
  loading: boolean;
  error: string | null;
  token: string;
}) {
  if (!own) return <p className="text-center text-xs text-zinc-500">{accountsNote(mode)}</p>;
  if (loading) return <div className="flex justify-center"><Spinner className="h-4 w-4 text-zinc-400" /></div>;
  if (error || !needs) return <p className="text-center text-sm text-red-600">{error}</p>;
  const mine = needs.systems.filter((s) => s.owner === "you");
  const theirs = needs.systems.filter((s) => s.owner === "publisher");
  const toConnect = mine.filter((s) => s.status !== "ready");
  return (
    <div className="space-y-3">
      {needs.systems.length > 0 && (
        <div className="flex flex-wrap items-center justify-center gap-1.5 text-xs">
          <span className="text-zinc-500">Uses your accounts:</span>
          {mine.map((s) => (
            <span key={s.system} className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-zinc-700">
              {s.status === "ready" ? <Check className="h-3 w-3 text-emerald-700" /> : <Circle className="h-2.5 w-2.5 text-zinc-400" />}
              {s.server_name || s.system}
            </span>
          ))}
          {theirs.map((s) => (
            <span key={s.system} className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-zinc-500" title="Uses the sharer's account">
              {s.server_name || s.system} · sharer&apos;s
            </span>
          ))}
        </div>
      )}
      {toConnect.length > 0 && (
        <div className="mx-auto max-w-md rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="mb-2 text-sm font-medium text-zinc-900">Connect first</p>
          <NeedsList token={token} statuses={toConnect} light />
        </div>
      )}
      {needs.problems.length > 0 && toConnect.length === 0 && <p className="text-center text-sm text-amber-700">{needs.problems.join(" ")}</p>}
    </div>
  );
}

function InputField({ v, value, onChange }: { v: InputVariable; value: string; onChange: (x: string) => void }) {
  return (
    <Field label={`${v.label || v.name}${v.required ? " *" : ""}`} hint={v.description || undefined}>
      {v.type === "boolean" ? (
        <Select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">—</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </Select>
      ) : (
        <Input type={v.type === "number" ? "number" : "text"} value={value} onChange={(e) => onChange(e.target.value)} />
      )}
    </Field>
  );
}

function StatusDot({ run }: { run: SharedRun }) {
  const color = run.status === "succeeded" ? "bg-[var(--success)]" : run.status === "failed" ? "bg-[var(--danger)]" : run.status === "waiting" ? "bg-[var(--warning)]" : run.status === "cancelled" ? "bg-zinc-400" : "animate-pulse bg-[var(--accent-hover)]";
  return <span className={cn("h-2 w-2 shrink-0 rounded-full", color)} title={run.status} />;
}

/** "▸ 3 steps" above the answer; while it runs, the step it's on. Open: each step and where it got. */
function Steps({ steps, running }: { steps: SharedStep[]; running: boolean }) {
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;
  const now = steps.find((s) => s.status === "running" || s.status === "waiting");
  const done = steps.filter((s) => s.status === "succeeded").length;
  const failed = steps.filter((s) => s.status === "failed").length;
  const summary = running
    ? now ? `${now.title}… (step ${steps.indexOf(now) + 1} of ${steps.length})` : `Working… ${done} of ${steps.length} done`
    : `${steps.length} step${steps.length === 1 ? "" : "s"}${failed ? `, ${failed} failed` : ""}`;
  return (
    <div className="mb-2">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-900 cursor-pointer">
        <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
        {summary}
      </button>
      {open && (
        <ol className="mt-1.5 space-y-1 border-l-2 border-zinc-200 pl-3">
          {steps.map((s) => (
            <li key={s.id} className="flex items-center gap-2 text-xs text-zinc-700">
              {s.status === "succeeded" ? <Check className="h-3.5 w-3.5 text-emerald-700" />
                : s.status === "failed" ? <XCircle className="h-3.5 w-3.5 text-red-600" />
                  : s.status === "running" ? <Spinner className="h-3.5 w-3.5 text-zinc-500" />
                    : s.status === "waiting" ? <ShieldAlert className="h-3.5 w-3.5 text-amber-700" />
                      : <Circle className="h-3 w-3 text-zinc-400" />}
              <span className={cn(s.status === "skipped" && "text-zinc-500 line-through")}>{s.title}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** One question and its answer, the way a chat shows it. */
function Turn({
  run, live, kind, own, token, onRetry, onDecided,
}: { run: SharedRun; live: string; kind: "agent" | "workflow"; own: boolean; token: string; onRetry?: () => void; onDecided: () => void }) {
  const [details, setDetails] = useState(false);
  const running = !DONE.has(run.status);
  return (
    <div className="space-y-6" aria-live="polite">
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[var(--surface-strong)] px-4 py-2.5 text-sm text-zinc-900">
          {run.input || "(ran with its inputs)"}
        </div>
      </div>
      <div className="flex gap-3">
        <TypeIcon kind={kind} size="sm" live={running} />
        <div className="min-w-0 flex-1 pt-0.5">
          <Steps steps={run.steps ?? []} running={running} />
          {run.status === "succeeded" ? (
            <AnswerView text={run.output ?? ""} />
          ) : run.status === "failed" || run.status === "cancelled" ? (
            <p className="text-sm text-red-600">{run.error || "It couldn't finish this request."}</p>
          ) : run.waiting_for === "approval" ? (
            <p className="flex items-start gap-2 text-sm text-zinc-700">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
              {own && run.approvals.length > 0
                ? run.approvals.some((a) => a.payload.outbound) ? "Here's what it wrote. Send it?" : "It needs your OK before going on:"
                : "Waiting for whoever shared this to approve a step. You can leave — the answer will be under History."}
            </p>
          ) : live ? (
            <MarkdownView text={live + " ▍"} />
          ) : (
            <p className="flex items-center gap-2 text-sm text-zinc-500"><Spinner className="h-4 w-4" /> Working on it…</p>
          )}
          {run.approvals.map((a) => <div key={a.id} className="mt-2"><ApprovalCard approval={a} token={token} onDone={onDecided} /></div>)}
          {run.sources.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
              Sources
              {run.sources.map((s) =>
                /^https?:\/\//.test(s) ? (
                  <a key={s} href={s} target="_blank" rel="noopener noreferrer" className="max-w-[16rem] truncate rounded-md bg-zinc-100 px-2 py-0.5 text-zinc-700 hover:text-zinc-900">{s.replace(/^https?:\/\/(www\.)?/, "")}</a>
                ) : (
                  <span key={s} className="rounded-md bg-zinc-100 px-2 py-0.5 text-zinc-700">{s}</span>
                ),
              )}
            </div>
          )}
          {!running && (
            <>
              <div className="mt-2 flex items-center gap-0.5">
                {run.output && <CopyButton text={run.output} />}
                {onRetry && (
                  <button type="button" onClick={onRetry} aria-label="Ask again" title="Ask the same thing again" className="inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer">
                    <RotateCw className="h-4 w-4" />
                  </button>
                )}
                <button type="button" onClick={() => setDetails((d) => !d)} aria-expanded={details} aria-label="Details" title="Time, tokens and cost" className={cn("inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer", details && "bg-zinc-100 text-zinc-900")}>
                  <Info className="h-4 w-4" />
                </button>
              </div>
              {details && (
                <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums text-zinc-500">
                  <span>{new Date(run.created_at).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
                  {run.duration_ms != null && <span>Took {formatDuration(run.duration_ms)}</span>}
                  {run.tokens ? <span>{formatTokens(run.tokens)} tokens{run.cost_usd != null ? ` · ${formatCost(run.cost_usd)}` : ""}</span> : null}
                  <span>Version {run.version}</span>
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

