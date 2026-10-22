"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, CircleDashed, Clock, ExternalLink, LogIn, Network, Plug, Send, ShieldAlert, Square, UserPlus } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field, Textarea } from "@/components/builder/fields";
import { ApprovalCard } from "@/components/builder/approval-card";
import { NeedsList } from "@/components/builder/tool-needs";
import { StreamToggle } from "@/components/builder/stream-toggle";
import { ApiError } from "@/lib/api";
import { sharedApi } from "@/lib/builder/api";
import type { InputVariable, SharedRun, ToolMode } from "@/lib/builder/types";
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

/**
 * A share link (/r/{slug}): what was shared, open to anyone; signing in runs
 * it. On a "publisher" link runs use the sharer's tools, so anything that
 * would change data waits for THEIR approval — this page shows that wait. On
 * a "visitor" link they use the person's own: they connect what's missing
 * here first, and decide their own approvals here too. A "mixed" link is a
 * visitor one where some apps are the sharer's — their account, their OK.
 */
export default function SharedPage() {
  const { slug } = useParams<{ slug: string }>();
  const token = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  // The saved sign-in is only readable after the first client render.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const info = useQuery({ queryKey: ["shared-info", slug], queryFn: () => sharedApi.info(slug), retry: false });
  const authHref = (mode: "login" | "signup") => `/auth?next=${encodeURIComponent(`/r/${slug}`)}${mode === "signup" ? "&mode=signup" : ""}`;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col gap-4 px-4 py-8 sm:py-12">
      {info.isLoading ? (
        <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-zinc-400" /></div>
      ) : info.isError || !info.data ? (
        <div className="rounded-xl border border-zinc-200 bg-white p-6 text-center">
          <p className="text-sm font-medium text-zinc-900">{info.error instanceof ApiError ? info.error.message : "This link couldn't be opened."}</p>
          <p className="mt-1 text-xs text-zinc-500">Ask whoever sent it for a new one.</p>
        </div>
      ) : (
        <>
          <header className="rounded-xl border border-zinc-200 bg-white p-5">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-600/15 text-indigo-400">
                {info.data.kind === "workflow" ? <Network className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
              </span>
              <div className="min-w-0">
                <h1 className="text-lg font-semibold text-zinc-900">{info.data.name}</h1>
                {info.data.shared_by && <p className="text-xs text-zinc-500">Shared by {info.data.shared_by}</p>}
              </div>
            </div>
            {info.data.description && <p className="mt-3 whitespace-pre-wrap text-sm text-zinc-700">{info.data.description}</p>}
          </header>

          {!mounted ? null : !token || !user ? (
            <div className="rounded-xl border border-zinc-200 bg-white p-5 text-center">
              <p className="text-sm font-medium text-zinc-900">Sign in to use it</p>
              <p className="mt-1 text-xs text-zinc-500">It&apos;s free. You&apos;ll come straight back here.</p>
              <div className="mt-4 flex justify-center gap-2">
                <Link href={authHref("login")} className={buttonVariants({ variant: "outline" })}><LogIn /> Log in</Link>
                <Link href={authHref("signup")} className={buttonVariants()}><UserPlus /> Sign up</Link>
              </div>
            </div>
          ) : (
            <Runner slug={slug} token={token} inputs={info.data.inputs} kind={info.data.kind} limit={info.data.per_user_daily_limit} toolMode={info.data.tool_mode} />
          )}

          {mounted && user && (
            <p className="text-center text-xs text-zinc-500">
              Signed in as {user.email} ·{" "}
              <button type="button" onClick={logout} className="underline hover:text-zinc-800 cursor-pointer">Sign out</button>
            </p>
          )}
        </>
      )}
    </main>
  );
}

function Runner({
  slug, token, inputs, kind, limit, toolMode,
}: { slug: string; token: string; inputs: InputVariable[]; kind: "agent" | "workflow"; limit: number | null; toolMode: ToolMode }) {
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

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Streaming: start at once and watch it being written; otherwise wait a little for the whole answer.
      const run = await sharedApi.run(token, slug, { input: text.trim(), variables: variables(), wait_seconds: streamOn ? 0 : 20, stream: streamOn });
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

  const missing = inputs.some((v) => v.required && !(values[v.name] ?? "").trim());
  const blocked = own && (!needs.data || needs.data.problems.length > 0);
  const canSend = !busy && !missing && !blocked && (kind === "workflow" || !!text.trim());

  return (
    <>
      {own && (
        <section className="space-y-2 rounded-xl border border-zinc-200 bg-white p-5">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
            <Plug className="h-4 w-4 text-sky-500" /> {toolMode === "mixed" ? "Uses some of your accounts" : "Uses your own accounts"}
          </h2>
          <p className="text-xs text-zinc-500">
            It works with apps you connect, as you — and asks you before it changes anything in them. Whoever shared it can see that you used it, not what was in it.
          </p>
          {needs.isLoading ? (
            <Spinner className="h-4 w-4 text-zinc-400" />
          ) : needs.isError ? (
            <p className="text-xs text-red-600">{errorText(needs.error)}</p>
          ) : (
            <>
              {needs.data!.systems.some((x) => x.owner === "you") && <NeedsList token={token} statuses={needs.data!.systems.filter((x) => x.owner === "you")} light />}
              {needs.data!.systems.some((x) => x.owner === "publisher") && (
                <div className="space-y-1 border-t border-zinc-100 pt-2">
                  <p className="text-xs font-medium text-zinc-700">With the sharer&apos;s account (they approve what it changes there):</p>
                  {needs.data!.systems.filter((x) => x.owner === "publisher").map((x) => (
                    <p key={x.system} className="flex items-center gap-1.5 text-[11.5px] text-zinc-700">
                      {x.status === "ready" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> : <CircleDashed className="h-3.5 w-3.5 text-zinc-400" />}
                      {x.server_name || x.system}
                    </p>
                  ))}
                </div>
              )}
              {needs.data!.problems.map((p) => <p key={p} className="text-xs text-amber-700">• {p}</p>)}
              {needs.data!.problems.length === 0 && <p className="text-xs text-emerald-600">All set.</p>}
            </>
          )}
        </section>
      )}

      <section className="space-y-3 rounded-xl border border-zinc-200 bg-white p-5">
        {inputs.map((v) => (
          <Field key={v.name} label={`${v.label || v.name}${v.required ? "" : " (optional)"}`} hint={v.description || undefined}>
            {v.type === "boolean" ? (
              <select
                value={values[v.name] ?? ""}
                onChange={(e) => setValues({ ...values, [v.name]: e.target.value })}
                className="h-9 w-full rounded-md border border-zinc-300 bg-white px-2 text-sm"
              >
                <option value="">—</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            ) : (
              <Input className="h-9" type={v.type === "number" ? "number" : "text"} value={values[v.name] ?? ""} onChange={(e) => setValues({ ...values, [v.name]: e.target.value })} />
            )}
          </Field>
        ))}
        <Field label={kind === "agent" ? "Your question" : inputs.length ? "Anything to add (optional)" : "Your request (optional)"}>
          <Textarea
            rows={3}
            value={text}
            maxLength={8000}
            placeholder="Type here…"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSend) void submit();
            }}
          />
        </Field>
        {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-zinc-500">{limit ? `Up to ${limit} runs a day.` : ""}</p>
          <StreamToggle className="ml-auto" />
          <Button disabled={!canSend} onClick={() => void submit()}>
            {busy ? <Spinner className="h-4 w-4" /> : <Send />} Run
          </Button>
        </div>
      </section>

      {current && (
        <Result run={current} live={live?.runId === current.run_id ? live.text : ""} slug={slug} token={token} own={own} onChange={setCurrent} />
      )}

      {(history.data ?? []).length > 0 && (
        <section className="rounded-xl border border-zinc-200 bg-white">
          <h2 className="border-b border-zinc-100 px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">Your runs</h2>
          <ul className="max-h-72 divide-y divide-zinc-100 overflow-y-auto">
            {history.data!.map((r) => (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => open(r)}
                  className={cn("flex w-full items-center gap-3 px-5 py-2.5 text-left hover:bg-zinc-50 cursor-pointer", current?.run_id === r.run_id && "bg-zinc-50")}
                >
                  <StatusDot run={r} />
                  <span className="min-w-0 flex-1 truncate text-sm text-zinc-800">{r.input || "(no message)"}</span>
                  <span className="shrink-0 text-xs text-zinc-500">{ago(r.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function StatusDot({ run }: { run: SharedRun }) {
  const color = run.status === "succeeded" ? "bg-emerald-500" : run.status === "failed" ? "bg-red-500" : run.status === "waiting" ? "bg-amber-500" : run.status === "cancelled" ? "bg-zinc-400" : "animate-pulse bg-sky-500";
  return <span className={cn("h-2 w-2 shrink-0 rounded-full", color)} title={run.status} />;
}

function Result({
  run, live, slug, token, own, onChange,
}: { run: SharedRun; live: string; slug: string; token: string; own: boolean; onChange: (r: SharedRun) => void }) {
  const [stopping, setStopping] = useState(false);
  const stop = async () => {
    setStopping(true);
    try {
      onChange(await sharedApi.cancel(token, slug, run.run_id));
    } catch {
      /* it may have just finished */
    } finally {
      setStopping(false);
    }
  };

  // After a decision, show where the run went without waiting for the next poll.
  const reload = async () => {
    try {
      onChange(await sharedApi.get(token, slug, run.run_id));
    } catch {
      /* the poll picks it up */
    }
  };

  return (
    <section className="space-y-3 rounded-xl border border-zinc-200 bg-white p-5" aria-live="polite">
      {run.input && <p className="rounded-lg bg-zinc-100 px-3 py-2 text-sm text-zinc-800">{run.input}</p>}
      {run.status === "succeeded" ? (
        <>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-900">{run.output}</p>
          {run.sources.length > 0 && (
            <div className="space-y-1 border-t border-zinc-100 pt-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Sources</p>
              {run.sources.map((s) => (
                <a key={s} href={s} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 truncate text-xs text-indigo-500 hover:text-indigo-400">
                  <ExternalLink className="h-3 w-3 shrink-0" /> <span className="truncate">{s}</span>
                </a>
              ))}
            </div>
          )}
        </>
      ) : run.status === "failed" || run.status === "cancelled" ? (
        <p className="text-sm text-red-600">{run.error || "It couldn't finish this request."}</p>
      ) : (
        <div className="flex items-center gap-2 text-sm text-zinc-700">
          {run.waiting_for === "approval" ? (
            own && run.approvals.length > 0 ? (
              <><ShieldAlert className="h-4 w-4 shrink-0 text-amber-500" /> It needs your OK before going on:</>
            ) : (
              <><ShieldAlert className="h-4 w-4 shrink-0 text-amber-500" /> Waiting for whoever shared this to approve a step. You can leave — the answer will be under Your runs.</>
            )
          ) : (
            <><Spinner className="h-4 w-4 shrink-0 text-zinc-400" /> {live ? "Writing…" : "Working on it…"}</>
          )}
          <button
            type="button"
            onClick={() => void stop()}
            disabled={stopping}
            className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-600 hover:text-zinc-900 disabled:opacity-50 cursor-pointer"
          >
            {stopping ? <Spinner className="h-3 w-3" /> : <Square className="h-3 w-3" />} Stop
          </button>
        </div>
      )}
      {!DONE.has(run.status) && live && (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-900">{live}<span className="animate-pulse">▍</span></p>
      )}
      {run.approvals.map((a) => <ApprovalCard key={a.id} approval={a} token={token} onDone={() => void reload()} />)}
      <p className="flex items-center gap-1 text-xs text-zinc-500"><Clock className="h-3 w-3" /> {ago(run.created_at)}</p>
    </section>
  );
}
