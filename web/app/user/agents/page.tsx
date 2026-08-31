"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Bot,
  Sparkles,
  Play,
  Search,
  Wrench,
  ArrowRight,
  CircleDot,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import {
  vendorApi,
  ApiError,
  type CompiledAgentSpec,
  type RunAgentResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

export default function UserAgentsPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const [query, setQuery] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [runResult, setRunResult] = useState<RunAgentResponse | null>(null);
  const [compileResult, setCompileResult] = useState<CompiledAgentSpec | null>(null);

  // Authorized catalog (semantic when catalogQuery set)
  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: ["catalog", accessToken, catalogQuery],
    queryFn: () =>
      vendorApi.getCatalog(accessToken, catalogQuery ? { q: catalogQuery, top_k: 10 } : undefined),
    enabled: !!accessToken,
  });

  const compileMutation = useMutation({
    mutationFn: (q: string) => vendorApi.compileAgent(accessToken, { query: q, top_k: 5 }),
    onSuccess: (spec) => setCompileResult(spec),
  });

  const runMutation = useMutation({
    mutationFn: (q: string) => vendorApi.runAgent(accessToken, { query: q, top_k: 5 }),
    onSuccess: (res) => {
      setRunResult(res);
      setCompileResult(res.spec);
    },
  });

  const handleCompile = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setRunResult(null);
    compileMutation.mutate(query.trim());
  };

  const handleRun = () => {
    if (!query.trim()) return;
    setCompileResult(null);
    runMutation.mutate(query.trim());
  };

  const compileError = compileMutation.isError
    ? compileMutation.error instanceof ApiError
      ? compileMutation.error.message
      : "Failed to compile agent"
    : null;
  const runError = runMutation.isError
    ? runMutation.error instanceof ApiError
      ? runMutation.error.message
      : "Failed to run agent"
    : null;

  return (
    <ProtectedDashboard
      path="/user"
      title="AI Compiler"
      description="Describe an agent in natural language — the compiler picks your authorized tools and LangGraph executes the plan."
    >
      <div className="mt-6 flex items-center justify-between">
        <a href="/user" className="text-sm text-zinc-500 hover:text-zinc-800 cursor-pointer">
          ← Back to workspace
        </a>
      </div>

      {/* NL prompt */}
      <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-indigo-600" />
          <h2 className="text-lg font-semibold text-zinc-900">Compile an agent</h2>
        </div>
        <p className="mt-1 text-sm text-zinc-500">
          Only tools you&apos;re authorized for (global tools, or tools granted to your tenant)
          can be selected.
        </p>
        <form onSubmit={handleCompile} className="mt-4 flex gap-2">
          <Input
            placeholder="e.g. verify a vendor invoice over 5000 and notify finance"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button type="submit" disabled={compileMutation.isPending}>
            {compileMutation.isPending ? <Spinner /> : <Sparkles className="h-4 w-4 mr-1" />}
            Compile
          </Button>
          <Button type="button" variant="outline" onClick={handleRun} disabled={runMutation.isPending}>
            {runMutation.isPending ? <Spinner /> : <Play className="h-4 w-4 mr-1" />} Run
          </Button>
        </form>
        {(compileError || runError) && (
          <p className="mt-3 text-xs text-red-600">{compileError || runError}</p>
        )}
      </div>

      {/* Compiled spec + run results */}
      {(compileResult || runResult) && (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <SpecCard spec={runResult?.spec ?? compileResult!} />
          {runResult && <ResultsCard result={runResult} />}
        </div>
      )}

      {/* Authorized catalog */}
      <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-zinc-100 pb-4">
          <div className="flex items-center gap-2">
            <Wrench className="h-5 w-5 text-sky-600" />
            <div>
              <h2 className="text-lg font-semibold text-zinc-900">Your authorized catalog</h2>
              <p className="text-sm text-zinc-500">Tools the compiler may bind for you.</p>
            </div>
          </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input
              placeholder="Semantic search tools…"
              value={catalogQuery}
              onChange={(e) => setCatalogQuery(e.target.value)}
              className="pl-9 sm:w-64"
            />
          </div>
        </div>

        {catalogLoading ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-6 w-6 text-zinc-500" />
          </div>
        ) : (catalog?.tools ?? []).length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-400">
            No tools available. Ask a vendor admin to register or grant tools.
          </p>
        ) : (
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {catalog!.tools.map((t) => (
              <li key={t.id} className="rounded-lg border border-zinc-200 p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-medium text-zinc-900">{t.name}</span>
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600">
                    {t.category}
                  </span>
                </div>
                <p className="mt-1 text-xs text-zinc-500">{t.description || "—"}</p>
                <div className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                  <span className="font-mono">{t.method}</span>
                  <span>·</span>
                  <span>{t.endpoint_url ? "live endpoint" : "simulated"}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-zinc-400">{catalog?.count ?? 0} tools</p>
      </div>
    </ProtectedDashboard>
  );
}

function SpecCard({ spec }: { spec: CompiledAgentSpec }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
      <h3 className="text-lg font-semibold text-zinc-900">Compiled spec</h3>
      <p className="mt-1 text-sm text-zinc-500">
        <span className="font-medium text-zinc-700">{spec.agent_name}</span>
        {spec.description ? ` — ${spec.description}` : ""}
      </p>

      {spec.nodes.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-400">
          No tools matched your request from your authorized catalog.
        </p>
      ) : (
        <ol className="mt-4 space-y-3">
          {spec.nodes.map((n, i) => (
            <li key={n.id} className="rounded-lg border border-zinc-200 p-3">
              <div className="flex items-center gap-2">
                <CircleDot className="h-4 w-4 text-indigo-500" />
                <span className="text-xs font-semibold uppercase text-zinc-400">
                  Step {i + 1} · {n.node_type ?? "tool.call"}
                </span>
              </div>
              <div className="mt-1 font-mono text-sm text-zinc-900">{n.id}</div>
              {n.description && (
                <p className="text-xs text-zinc-500">{n.description}</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                {n.tool_id ? (
                  <span className="rounded bg-emerald-50 px-2 py-0.5 font-mono text-emerald-700">
                    tool: {n.tool_id}
                  </span>
                ) : (
                  <span className="rounded bg-amber-50 px-2 py-0.5 text-amber-700">
                    unconfigured (no matching tool)
                  </span>
                )}
                {n.unconfigured && (
                  <span className="text-amber-600">simulated</span>
                )}
              </div>
              {n.args && Object.keys(n.args).length > 0 && (
                <pre className="mt-2 overflow-x-auto rounded bg-zinc-50 p-2 text-xs text-zinc-600">
                  {JSON.stringify(n.args, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}

      {spec.edges.length > 0 && (
        <div className="mt-4 text-xs text-zinc-500">
          <span className="font-semibold">Edges:</span>{" "}
          {spec.edges.map((e, i) => (
            <span key={i} className="font-mono">
              {e.source} → {e.target}
              {e.condition ? ` (${e.condition})` : ""}
              {i < spec.edges.length - 1 ? ", " : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultsCard({ result }: { result: RunAgentResponse }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
      <h3 className="text-lg font-semibold text-zinc-900">Execution results</h3>
      <p className="mt-1 text-sm text-zinc-500">
        LangGraph ran {result.trace.length} node{result.trace.length === 1 ? "" : "s"}.
      </p>

      <ul className="mt-4 space-y-3">
        {result.trace.map((t, i) => {
          const res = result.results[t.node] as Record<string, unknown> | undefined;
          const simulated = (res as { simulated?: boolean } | undefined)?.simulated;
          return (
            <li key={t.node} className="rounded-lg border border-zinc-200 p-3">
              <div className="flex items-center gap-2">
                <ArrowRight className="h-4 w-4 text-zinc-400" />
                <span className="text-xs font-semibold uppercase text-zinc-400">
                  {i + 1}. {t.node}
                </span>
                {simulated === true ? (
                  <span className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                    simulated
                  </span>
                ) : (
                  <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                    live call
                  </span>
                )}
              </div>
              <pre className="mt-2 overflow-x-auto rounded bg-zinc-50 p-2 text-xs text-zinc-600">
                {JSON.stringify(res ?? null, null, 2)}
              </pre>
            </li>
          );
        })}
      </ul>
    </div>
  );
}