"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Bot,
  Sparkles,
  Play,
  Search,
  Server,
  Wrench,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import {
  vendorApi,
  ApiError,
  type ToolSearchResponse,
  type ToolCallPlanResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

export default function UserAgentsPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const [query, setQuery] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [searchResult, setSearchResult] = useState<ToolSearchResponse | null>(null);
  const [planResult, setPlanResult] = useState<ToolCallPlanResponse | null>(null);

  // Authorized catalog (semantic when catalogQuery set)
  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: ["catalog", accessToken, catalogQuery],
    queryFn: () =>
      vendorApi.getCatalog(accessToken, catalogQuery ? { q: catalogQuery, top_k: 10 } : undefined),
    enabled: !!accessToken,
  });

  // "Compile": two-stage semantic search -> which tools could answer this?
  const searchMutation = useMutation({
    mutationFn: (q: string) =>
      vendorApi.searchCatalogTools(accessToken, { q, top_k_servers: 5, top_k_tools: 5 }),
    onSuccess: (res) => setSearchResult(res),
  });

  // "Run": pick one tool + fill its arguments via LLM — still doesn't call it.
  const planMutation = useMutation({
    mutationFn: (q: string) =>
      vendorApi.planToolCall(accessToken, { q, top_k_servers: 5, top_k_tools: 3 }),
    onSuccess: (res) => setPlanResult(res),
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setPlanResult(null);
    searchMutation.mutate(query.trim());
  };

  const handlePlan = () => {
    if (!query.trim()) return;
    setSearchResult(null);
    planMutation.mutate(query.trim());
  };

  const searchError = searchMutation.isError
    ? searchMutation.error instanceof ApiError
      ? searchMutation.error.message
      : "Failed to search the catalog"
    : null;
  const planError = planMutation.isError
    ? planMutation.error instanceof ApiError
      ? planMutation.error.message
      : "Failed to plan a tool call"
    : null;

  return (
    <ProtectedDashboard
      path="/user"
      title="AI Compiler"
      description="Describe what you need in natural language — semantic search picks the matching MCP server and tool from your authorized catalog."
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
          <h2 className="text-lg font-semibold text-zinc-900">Find a tool</h2>
        </div>
        <p className="mt-1 text-sm text-zinc-500">
          Only servers you&apos;re authorized for (global servers, or servers
          granted to your tenant) can be matched.
        </p>
        <form onSubmit={handleSearch} className="mt-4 flex gap-2">
          <Input
            placeholder="e.g. how do I get all pending invoices"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button type="submit" disabled={searchMutation.isPending}>
            {searchMutation.isPending ? <Spinner /> : <Sparkles className="h-4 w-4 mr-1" />}
            Compile
          </Button>
          <Button type="button" variant="outline" onClick={handlePlan} disabled={planMutation.isPending}>
            {planMutation.isPending ? <Spinner /> : <Play className="h-4 w-4 mr-1" />} Run
          </Button>
        </form>
        <p className="mt-2 text-xs text-zinc-400">
          <span className="font-medium">Compile</span> lists matching tools + their parameters.{" "}
          <span className="font-medium">Run</span> additionally asks an LLM to fill in those
          parameters from your text — neither calls the tool.
        </p>
        {(searchError || planError) && (
          <p className="mt-3 text-xs text-red-600">{searchError || planError}</p>
        )}
      </div>

      {/* Search / plan results */}
      {searchResult && <SearchResultsCard result={searchResult} />}
      {planResult && <PlanResultCard result={planResult} />}

      {/* Authorized catalog */}
      <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-zinc-100 pb-4">
          <div className="flex items-center gap-2">
            <Server className="h-5 w-5 text-sky-600" />
            <div>
              <h2 className="text-lg font-semibold text-zinc-900">Your authorized catalog</h2>
              <p className="text-sm text-zinc-500">MCP servers available to you.</p>
            </div>
          </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input
              placeholder="Semantic search servers…"
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
        ) : (catalog?.servers ?? []).length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-400">
            No servers available. Ask a vendor admin to register or grant servers.
          </p>
        ) : (
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {catalog!.servers.map((s) => (
              <li key={s.id} className="rounded-lg border border-zinc-200 p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-medium text-zinc-900">{s.name}</span>
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600">
                    {s.transport}
                  </span>
                </div>
                <p className="mt-1 text-xs text-zinc-500">{s.description || "—"}</p>
                <div className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                  <span>{s.server_url ? "live endpoint" : "simulated"}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-zinc-400">{catalog?.count ?? 0} servers</p>
      </div>
    </ProtectedDashboard>
  );
}

function SearchResultsCard({ result }: { result: ToolSearchResponse }) {
  return (
    <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
      <div className="flex items-center gap-2">
        <Wrench className="h-5 w-5 text-indigo-500" />
        <h3 className="text-lg font-semibold text-zinc-900">Matched tools</h3>
      </div>

      {result.results.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-400">
          No tools matched your request from your authorized catalog.
        </p>
      ) : (
        <ol className="mt-4 space-y-3">
          {result.results.map((r, i) => (
            <li key={r.tool_id} className="rounded-lg border border-zinc-200 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase text-zinc-400">
                  {i + 1}. {r.tool_name}
                </span>
                {r.score != null && (
                  <span className="rounded bg-zinc-50 px-2 py-0.5 font-mono text-xs text-zinc-500">
                    {r.score.toFixed(3)}
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs text-zinc-500">{r.tool_description || "—"}</p>
              <span className="mt-2 inline-block rounded bg-emerald-50 px-2 py-0.5 font-mono text-xs text-emerald-700">
                server: {r.server_name}
              </span>
              {r.input_schema && (
                <pre className="mt-2 overflow-x-auto rounded bg-zinc-50 p-2 text-xs text-zinc-600">
                  {JSON.stringify(r.input_schema, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function PlanResultCard({ result }: { result: ToolCallPlanResponse }) {
  return (
    <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
      <h3 className="text-lg font-semibold text-zinc-900">Proposed tool call</h3>
      <p className="mt-1 text-xs text-amber-600">Not executed — no MCP call is made here.</p>

      {!result.plan ? (
        <p className="mt-4 text-sm text-zinc-400">
          {result.message || "No confident tool match for this request."}
        </p>
      ) : (
        <div className="mt-4 rounded-lg border border-zinc-200 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-sm font-medium text-zinc-900">
              {result.plan.tool_name}
            </span>
            <span className="rounded bg-emerald-50 px-2 py-0.5 font-mono text-xs text-emerald-700">
              server: {result.plan.server_name}
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-400">model: {result.plan.model}</p>
          <pre className="mt-2 overflow-x-auto rounded bg-zinc-50 p-2 text-xs text-zinc-600">
            {JSON.stringify(result.plan.arguments, null, 2)}
          </pre>
        </div>
      )}

      {result.candidates_considered.length > 0 && (
        <p className="mt-3 text-xs text-zinc-400">
          Considered: {result.candidates_considered.join(", ")}
        </p>
      )}
    </div>
  );
}
