"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ChevronRight, CircleDashed, FlaskConical, Play, Plus, Sparkles, Square, Trash2, X, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Field, Select, Textarea } from "@/components/builder/fields";
import { timeAgo } from "@/components/builder/version-history";
import { builderApi } from "@/lib/builder/api";
import type { TestCase, TestCategory, TestResult, TestRun } from "@/lib/builder/types";
import { cn } from "@/lib/utils";

export const CATEGORY_LABELS: Record<TestCategory, string> = {
  normal: "Normal",
  ambiguous: "Unclear request",
  knowledge_gap: "Knowledge gap",
  tools: "Tools",
  safety: "Sensitive data",
  injection: "Injection",
  out_of_scope: "Out of scope",
};
const DEFAULT_GENERATE: TestCategory[] = ["normal", "ambiguous", "knowledge_gap", "tools", "safety", "injection"];
const DIMENSION_LABELS = { behaviour: "Behaviour", knowledge: "Knowledge", tools: "Tools", safety: "Safety" } as const;

function scoreTone(score: number | null | undefined): string {
  if (score === null || score === undefined) return "text-zinc-400";
  return score >= 80 ? "text-emerald-600" : score >= 60 ? "text-amber-600" : "text-red-600";
}

function ResultIcon({ status }: { status: TestResult["status"] }) {
  if (status === "passed") return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" aria-label="Passed" />;
  if (status === "failed") return <XCircle className="h-4 w-4 shrink-0 text-red-500" aria-label="Failed" />;
  if (status === "error") return <XCircle className="h-4 w-4 shrink-0 text-zinc-400" aria-label="Couldn't run" />;
  return <Spinner className="h-4 w-4 shrink-0 text-sky-500" />;
}

/**
 * Test an agent or workflow: write cases (or have the AI write them), run them
 * all against the saved version, and see each case graded — with the score
 * kept per version, so a change that makes it worse shows.
 */
export function TestsPanel({
  kind,
  targetId,
  token,
  canManage,
  beforeRun,
  onClose,
}: {
  kind: "agent" | "workflow";
  targetId: string;
  token: string;
  canManage: boolean;
  /** Save unsaved changes first: tests run the saved version. */
  beforeRun?: () => Promise<boolean>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const casesKey = ["builder-tests", kind, targetId];
  const runsKey = ["builder-test-runs", kind, targetId];
  const [tab, setTab] = useState<"cases" | "results" | "history">("cases");
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong.");

  const cases = useQuery({ queryKey: casesKey, queryFn: () => builderApi.listTests(token, kind, targetId), enabled: !!token });
  const history = useQuery({ queryKey: runsKey, queryFn: () => builderApi.listTestRuns(token, kind, targetId), enabled: !!token });
  const currentId = openRunId ?? history.data?.[0]?.id ?? null;
  const current = useQuery({
    queryKey: ["builder-test-run", currentId],
    queryFn: () => builderApi.getTestRun(token, currentId!),
    enabled: !!token && !!currentId,
    // Live while it runs; a finished test run never changes.
    refetchInterval: (q) => ((q.state.data as TestRun | undefined)?.status === "running" ? 2000 : false),
  });
  useEffect(() => {
    if (current.data && current.data.status !== "running") void queryClient.invalidateQueries({ queryKey: runsKey });
  }, [current.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = useMutation({
    mutationFn: async () => {
      setError(null);
      if (beforeRun && !(await beforeRun())) throw new Error("Save the changes first: tests run the saved version.");
      return builderApi.startTestRun(token, kind, targetId);
    },
    onSuccess: (t) => {
      queryClient.setQueryData(["builder-test-run", t.id], t);
      setOpenRunId(t.id);
      setTab("results");
      void queryClient.invalidateQueries({ queryKey: runsKey });
    },
    onError: fail,
  });
  const cancel = useMutation({
    mutationFn: (id: string) => builderApi.cancelTestRun(token, id),
    onSuccess: (t) => queryClient.setQueryData(["builder-test-run", t.id], t),
    onError: fail,
  });

  const running = current.data?.status === "running";
  const latest = current.data;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b border-zinc-200 px-4 py-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900"><FlaskConical className="h-4 w-4" /> Tests</h2>
          <p className="text-xs text-zinc-500">Real runs, graded by AI. Actions that change data are simulated.</p>
        </div>
        <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-2 border-b border-zinc-200 px-4 py-3">
        {latest ? (
          <div className="flex items-center gap-3">
            <p className={cn("text-3xl font-bold tabular-nums", scoreTone(latest.score))}>{latest.score !== null ? `${latest.score}%` : "—"}</p>
            <div className="min-w-0 flex-1 text-xs text-zinc-600">
              <p className="font-medium text-zinc-900">
                {running ? `Running… ${latest.done}/${latest.total} done` : latest.status === "cancelled" ? "Cancelled" : `${latest.passed}/${latest.total} passed`}
              </p>
              <p>v{latest.definition_version} · {timeAgo(latest.created_at)}</p>
            </div>
          </div>
        ) : (
          <p className="text-xs text-zinc-500">Not tested yet.</p>
        )}
        {latest && Object.keys(latest.dimensions).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(DIMENSION_LABELS) as (keyof typeof DIMENSION_LABELS)[]).filter((d) => latest.dimensions[d] !== undefined).map((d) => (
              <span key={d} className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-700">
                {DIMENSION_LABELS[d]} <span className={cn("font-semibold", scoreTone(latest.dimensions[d]))}>{latest.dimensions[d]}%</span>
              </span>
            ))}
          </div>
        )}
        {running && latest && (
          <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100">
            <div className="h-full bg-sky-400 transition-all" style={{ width: `${(100 * latest.done) / Math.max(1, latest.total)}%` }} />
          </div>
        )}
        <div className="flex gap-2">
          <Button size="sm" disabled={start.isPending || running || !(cases.data ?? []).length} onClick={() => start.mutate()}>
            {start.isPending ? <Spinner className="h-4 w-4" /> : <Play />} Run {cases.data?.length ?? 0} test{cases.data?.length === 1 ? "" : "s"}
          </Button>
          {running && latest && (
            <Button size="sm" variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate(latest.id)}>
              <Square /> Stop
            </Button>
          )}
        </div>
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>

      <div className="flex border-b border-zinc-200 px-2 text-xs" role="tablist">
        {(["cases", "results", "history"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={cn("px-3 py-2 font-medium capitalize cursor-pointer", tab === t ? "border-b-2 border-indigo-600 text-indigo-700" : "text-zinc-500 hover:text-zinc-800")}
          >
            {t === "cases" ? `Cases (${cases.data?.length ?? 0})` : t}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "cases" && <CasesTab kind={kind} targetId={targetId} token={token} canManage={canManage} cases={cases.data ?? []} loading={cases.isLoading} />}
        {tab === "results" && (latest?.results ? <ResultsList results={latest.results} /> : <p className="px-4 py-6 text-center text-xs text-zinc-400">Run the tests to see results.</p>)}
        {tab === "history" && (
          <ol>
            {(history.data ?? []).map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => {
                    setOpenRunId(t.id);
                    setTab("results");
                  }}
                  className={cn("flex w-full items-center gap-3 border-b border-zinc-100 px-4 py-2.5 text-left hover:bg-zinc-50 cursor-pointer", t.id === currentId && "bg-indigo-50/60")}
                >
                  <span className={cn("w-12 text-lg font-bold tabular-nums", scoreTone(t.score))}>{t.score !== null ? `${t.score}%` : "—"}</span>
                  <span className="flex-1 text-xs text-zinc-600">
                    <span className="font-medium text-zinc-900">v{t.definition_version}</span> · {t.status === "running" ? "running" : t.status === "cancelled" ? "cancelled" : `${t.passed}/${t.total} passed`}
                    <span className="block text-zinc-400">{timeAgo(t.created_at)}</span>
                  </span>
                </button>
              </li>
            ))}
            {history.data?.length === 0 && <p className="px-4 py-6 text-center text-xs text-zinc-400">No test runs yet.</p>}
          </ol>
        )}
      </div>
    </div>
  );
}

function ResultsList({ results }: { results: TestResult[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ul>
      {results.map((r) => (
        <li key={r.id} className="border-b border-zinc-100 px-4 py-2.5">
          <button type="button" onClick={() => setOpen(open === r.id ? null : r.id)} className="flex w-full items-start gap-2 text-left cursor-pointer">
            <ResultIcon status={r.status} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-zinc-900">{r.title}</span>
              <span className="text-[11px] text-zinc-500">{CATEGORY_LABELS[r.category] ?? r.category}</span>
            </span>
            {r.score !== null && <span className={cn("text-xs font-semibold tabular-nums", scoreTone(r.score * 100))}>{Math.round(r.score * 100)}%</span>}
            {open === r.id ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
          </button>
          {r.reasoning && <p className="mt-1 pl-6 text-xs text-zinc-600">{r.reasoning}</p>}
          {open === r.id && (
            <dl className="mt-2 space-y-1.5 rounded-lg bg-zinc-50 p-2.5 text-xs">
              <dt className="font-medium text-zinc-500">Asked</dt>
              <dd className="whitespace-pre-wrap text-zinc-800">{r.input}</dd>
              <dt className="font-medium text-zinc-500">Expected</dt>
              <dd className="text-zinc-800">{r.expectation}</dd>
              <dt className="font-medium text-zinc-500">Answered</dt>
              <dd className="line-clamp-[12] whitespace-pre-wrap text-zinc-800">{r.answer || "—"}</dd>
            </dl>
          )}
        </li>
      ))}
    </ul>
  );
}

function CasesTab({
  kind,
  targetId,
  token,
  canManage,
  cases,
  loading,
}: {
  kind: "agent" | "workflow";
  targetId: string;
  token: string;
  canManage: boolean;
  cases: TestCase[];
  loading: boolean;
}) {
  const queryClient = useQueryClient();
  const key = ["builder-tests", kind, targetId];
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ input: "", expectation: "", category: "normal" as TestCategory });
  const [genCount, setGenCount] = useState(6);
  const [genCats, setGenCats] = useState<TestCategory[]>(DEFAULT_GENERATE);
  const [showGen, setShowGen] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong.");

  const create = useMutation({
    mutationFn: () => builderApi.createTest(token, kind, targetId, draft),
    onSuccess: () => {
      setDraft({ input: "", expectation: "", category: "normal" });
      setAdding(false);
      setError(null);
      void refresh();
    },
    onError: fail,
  });
  const generate = useMutation({
    mutationFn: () => builderApi.generateTests(token, kind, targetId, genCount, genCats),
    onSuccess: () => {
      setShowGen(false);
      setError(null);
      void refresh();
    },
    onError: fail,
  });
  const remove = useMutation({ mutationFn: (id: string) => builderApi.deleteTest(token, id), onSuccess: () => void refresh(), onError: fail });

  return (
    <div>
      {canManage && (
        <div className="flex gap-2 px-4 py-3">
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => { setShowGen((v) => !v); setAdding(false); }}>
            <Sparkles /> Write with AI
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => { setAdding((v) => !v); setShowGen(false); }}>
            <Plus /> Add a case
          </Button>
        </div>
      )}
      {error && <p className="px-4 pb-2 text-xs text-red-600">{error}</p>}

      {showGen && (
        <div className="mx-4 mb-3 space-y-2 rounded-lg border border-indigo-200 bg-indigo-50/30 p-3">
          <p className="text-xs text-zinc-600">The AI reads what this {kind} does and writes realistic cases, including the awkward ones people forget to try.</p>
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(CATEGORY_LABELS) as TestCategory[]).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setGenCats(genCats.includes(c) ? genCats.filter((x) => x !== c) : [...genCats, c])}
                className={cn("rounded-full border px-2 py-0.5 text-[11px] cursor-pointer", genCats.includes(c) ? "border-indigo-400 bg-indigo-100 text-indigo-800" : "border-zinc-200 text-zinc-500")}
              >
                {CATEGORY_LABELS[c]}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Select className="h-8 w-24 text-xs" value={genCount} onChange={(e) => setGenCount(Number(e.target.value))} aria-label="How many">
              {[3, 6, 9, 12].map((n) => <option key={n} value={n}>{n} cases</option>)}
            </Select>
            <Button size="sm" className="h-8" disabled={generate.isPending || genCats.length === 0} onClick={() => generate.mutate()}>
              {generate.isPending ? <Spinner className="h-4 w-4" /> : <Sparkles />} Write them
            </Button>
          </div>
        </div>
      )}

      {adding && (
        <div className="mx-4 mb-3 space-y-2 rounded-lg border border-zinc-200 p-3">
          <Field label="The request">
            <Textarea rows={2} value={draft.input} placeholder="What a user would type" onChange={(e) => setDraft({ ...draft, input: e.target.value })} />
          </Field>
          <Field label="A good response…" hint="Behaviour to look for, not exact words.">
            <Textarea rows={2} value={draft.expectation} placeholder="Says it can't share account numbers and offers to escalate" onChange={(e) => setDraft({ ...draft, expectation: e.target.value })} />
          </Field>
          <Field label="Kind">
            <Select value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value as TestCategory })}>
              {(Object.keys(CATEGORY_LABELS) as TestCategory[]).map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
            </Select>
          </Field>
          <Button size="sm" disabled={create.isPending || !draft.input.trim() || !draft.expectation.trim()} onClick={() => create.mutate()}>
            {create.isPending ? <Spinner className="h-4 w-4" /> : <Plus />} Add
          </Button>
        </div>
      )}

      {loading && <div className="flex justify-center py-6"><Spinner className="h-5 w-5 text-zinc-400" /></div>}
      {!loading && cases.length === 0 && !adding && !showGen && (
        <p className="px-4 py-6 text-center text-xs text-zinc-400">No test cases yet. Write some with AI, or add your own.</p>
      )}
      <ul>
        {cases.map((c) => (
          <li key={c.id} className="border-b border-zinc-100 px-4 py-2.5">
            <div className="flex items-start gap-2">
              <button type="button" onClick={() => setOpen(open === c.id ? null : c.id)} className="min-w-0 flex-1 text-left cursor-pointer">
                <span className="block text-sm font-medium text-zinc-900">{c.title}</span>
                <span className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-zinc-500">
                  <CircleDashed className="h-3 w-3" /> {CATEGORY_LABELS[c.category] ?? c.category}{c.source === "generated" ? " · by AI" : ""}
                </span>
              </button>
              {canManage && (
                <button type="button" aria-label={`Delete test ${c.title}`} onClick={() => remove.mutate(c.id)} className="text-zinc-300 hover:text-red-600 cursor-pointer">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {open === c.id && (
              <dl className="mt-2 space-y-1.5 rounded-lg bg-zinc-50 p-2.5 text-xs">
                <dt className="font-medium text-zinc-500">Request</dt>
                <dd className="whitespace-pre-wrap text-zinc-800">{c.input}</dd>
                <dt className="font-medium text-zinc-500">A good response</dt>
                <dd className="text-zinc-800">{c.expectation}</dd>
              </dl>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
