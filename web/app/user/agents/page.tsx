"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Bot,
  Sparkles,
  Play,
  Search,
  Server,
  Wrench,
  Link2,
  Unlink,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  X,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import {
  vendorApi,
  ApiError,
  type ToolSearchResponse,
  type ToolCallPlanResponse,
  type MCPServerEntry,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

export default function UserAgentsPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [searchResult, setSearchResult] = useState<ToolSearchResponse | null>(null);
  const [planResult, setPlanResult] = useState<ToolCallPlanResponse | null>(null);
  const [connectServer, setConnectServer] = useState<MCPServerEntry | null>(null);
  const [expandedToolsId, setExpandedToolsId] = useState<string | null>(null);
  const catalogSectionRef = useRef<HTMLDivElement>(null);

  // Authorized catalog (semantic when catalogQuery set)
  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: ["catalog", accessToken, catalogQuery],
    queryFn: () =>
      vendorApi.getCatalog(accessToken, catalogQuery ? { q: catalogQuery, top_k: 10 } : undefined),
    enabled: !!accessToken,
  });

  // The full, unfiltered catalog (ignores catalogQuery) — used only to
  // decide whether the user has connected *any* server yet, so that check
  // doesn't flicker false while they're mid-search in the catalog box below.
  const { data: fullCatalog } = useQuery({
    queryKey: ["catalog", accessToken, ""],
    queryFn: () => vendorApi.getCatalog(accessToken),
    enabled: !!accessToken,
  });
  const hasAnyConnectedServer = (fullCatalog?.servers ?? []).some((s) => s.connected);
  const serverById = useMemo(
    () => Object.fromEntries((fullCatalog?.servers ?? []).map((s) => [s.id, s])),
    [fullCatalog]
  );
  const connectServerById = (serverId: string) => {
    const entry = serverById[serverId];
    if (entry) setConnectServer(entry);
    else scrollToCatalog();
  };

  const connectMutation = useMutation({
    mutationFn: ({ id, credentials }: { id: string; credentials?: Record<string, string> | null }) =>
      vendorApi.connectMCPServerAsUser(accessToken, id, credentials),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["catalog", accessToken] });
      setConnectServer(null);
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: (id: string) => vendorApi.disconnectMCPServerAsUser(accessToken, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["catalog", accessToken] });
    },
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

  const scrollToCatalog = () => {
    catalogSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    if (!hasAnyConnectedServer) {
      scrollToCatalog();
      return;
    }
    setPlanResult(null);
    searchMutation.mutate(query.trim());
  };

  const handlePlan = () => {
    if (!query.trim()) return;
    if (!hasAnyConnectedServer) {
      scrollToCatalog();
      return;
    }
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
          <Button type="submit" disabled={searchMutation.isPending || !hasAnyConnectedServer}>
            {searchMutation.isPending ? <Spinner /> : <Sparkles className="h-4 w-4 mr-1" />}
            Compile
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handlePlan}
            disabled={planMutation.isPending || !hasAnyConnectedServer}
          >
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
        {!catalogLoading && !hasAnyConnectedServer && (
          <div className="mt-3 flex items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 p-3">
            <p className="text-xs text-amber-800">
              You haven&apos;t connected any MCP server yet. Connect one before you can compile
              or run a tool.
            </p>
            <button
              type="button"
              onClick={scrollToCatalog}
              className="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 cursor-pointer"
            >
              <Link2 className="h-3 w-3" /> Connect a server
            </button>
          </div>
        )}
      </div>

      {/* Search / plan results */}
      {searchResult && (
        <SearchResultsCard result={searchResult} serverById={serverById} onConnect={connectServerById} />
      )}
      {planResult && (
        <PlanResultCard result={planResult} serverById={serverById} onConnect={connectServerById} />
      )}

      {/* Authorized catalog */}
      <div ref={catalogSectionRef} className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
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
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="text-xs text-zinc-400">
                    {s.server_url ? "live endpoint" : "simulated"}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {s.connected ? (
                      <button
                        type="button"
                        onClick={() => setExpandedToolsId(expandedToolsId === s.id ? null : s.id)}
                        className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-50 cursor-pointer"
                        title="List tools"
                      >
                        <Wrench className="h-3 w-3" /> Tools ({s.bound_tools?.length ?? 0})
                        {expandedToolsId === s.id ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                      </button>
                    ) : (
                      <span className="text-xs italic text-zinc-400">Connect to view tools</span>
                    )}
                    {s.connected ? (
                      <>
                        <button
                          type="button"
                          onClick={() => setConnectServer(s)}
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 cursor-pointer"
                          title="Reconnect / update your credentials"
                        >
                          <CheckCircle2 className="h-3 w-3" /> Connected
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            if (confirm(`Disconnect your account from "${s.name}"? This removes your stored credentials.`)) {
                              disconnectMutation.mutate(s.id);
                            }
                          }}
                          disabled={disconnectMutation.isPending}
                          className="inline-flex items-center justify-center rounded-md border border-red-200 bg-red-50 p-1 text-red-600 hover:bg-red-100 disabled:opacity-50 cursor-pointer"
                          title="Disconnect your account"
                        >
                          <Unlink className="h-3 w-3" />
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConnectServer(s)}
                        className="inline-flex items-center gap-1 rounded-md border border-sky-200 bg-sky-50 px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 cursor-pointer"
                      >
                        <Link2 className="h-3 w-3" /> Connect
                      </button>
                    )}
                  </div>
                </div>
                {s.connected && expandedToolsId === s.id && (
                  <div className="mt-2 rounded-md border border-zinc-100 bg-zinc-50 p-2">
                    {s.bound_tools && s.bound_tools.length > 0 ? (
                      <ul className="space-y-1">
                        {s.bound_tools.map((t) => (
                          <li key={t} className="font-mono text-xs text-zinc-600">
                            {t}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-zinc-400">No tools discovered yet.</p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-zinc-400">{catalog?.count ?? 0} servers</p>
      </div>

      {connectServer && (
        <UserConnectModal
          server={connectServer}
          isPending={connectMutation.isPending}
          error={
            connectMutation.isError
              ? connectMutation.error instanceof ApiError
                ? connectMutation.error.message
                : "Connection failed"
              : null
          }
          onClose={() => {
            connectMutation.reset();
            setConnectServer(null);
          }}
          onSubmit={(credentials) => connectMutation.mutate({ id: connectServer.id, credentials })}
        />
      )}
    </ProtectedDashboard>
  );
}

function UserConnectModal({
  server,
  isPending,
  error,
  onClose,
  onSubmit,
}: {
  server: MCPServerEntry;
  isPending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (credentials?: Record<string, string> | null) => void;
}) {
  const fields = server.credential_fields ?? [];
  const [values, setValues] = useState<Record<string, string>>({});

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(fields.length > 0 ? values : null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Connect "{server.name}"</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <p className="text-xs text-zinc-500">
            This connects your own account to <span className="font-mono">{server.name}</span>.
            Your credentials are stored separately from anyone else&apos;s.
          </p>

          {fields.length > 0 ? (
            <div className="space-y-3">
              {fields.map((f) => (
                <div key={f}>
                  <label className="block text-xs font-medium text-zinc-600">{f}</label>
                  <Input
                    type="password"
                    value={values[f] || ""}
                    onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
                    placeholder={f}
                  />
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-md bg-zinc-50 p-3 text-xs text-zinc-500">
              No credentials required — click connect to verify access.
            </p>
          )}

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : <Link2 className="h-4 w-4 mr-1" />} Connect
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SearchResultsCard({
  result,
  serverById,
  onConnect,
}: {
  result: ToolSearchResponse;
  serverById: Record<string, MCPServerEntry>;
  onConnect: (serverId: string) => void;
}) {
  const blockedIds = result.needs_connection_server_ids ?? [];

  return (
    <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
      <div className="flex items-center gap-2">
        <Wrench className="h-5 w-5 text-indigo-500" />
        <h3 className="text-lg font-semibold text-zinc-900">Matched tools</h3>
      </div>

      {result.results.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-400">
          {blockedIds.length > 0
            ? "The best-matching tools are on servers you haven't connected yet."
            : "No tools matched your request from your authorized catalog."}
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

      {blockedIds.length > 0 && (
        <div className="mt-4 space-y-2 rounded-md border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs text-amber-800">
            {result.results.length > 0
              ? "More tools matched on servers you haven't connected yet:"
              : "Connect one of these servers to see its matching tools:"}
          </p>
          <div className="flex flex-wrap gap-2">
            {blockedIds.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onConnect(id)}
                className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 cursor-pointer"
              >
                <Link2 className="h-3 w-3" /> Connect {serverById[id]?.name ?? id}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PlanResultCard({
  result,
  serverById,
  onConnect,
}: {
  result: ToolCallPlanResponse;
  serverById: Record<string, MCPServerEntry>;
  onConnect: (serverId: string) => void;
}) {
  return (
    <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
      <h3 className="text-lg font-semibold text-zinc-900">Proposed tool call</h3>
      <p className="mt-1 text-xs text-amber-600">Not executed — no MCP call is made here.</p>

      {!result.plan ? (
        <div className="mt-4">
          <p className="text-sm text-zinc-400">
            {result.message || "No confident tool match for this request."}
          </p>
          {result.needs_connection_server_id && (
            <button
              type="button"
              onClick={() => onConnect(result.needs_connection_server_id!)}
              className="mt-3 inline-flex items-center gap-1 rounded-md border border-sky-200 bg-sky-50 px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 cursor-pointer"
            >
              <Link2 className="h-3 w-3" /> Connect{" "}
              {serverById[result.needs_connection_server_id]?.name ?? "server"}
            </button>
          )}
        </div>
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
