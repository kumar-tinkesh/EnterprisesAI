"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  PlugZap,
  Globe,
  Trash2,
  QrCode,
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
  type BridgeStatus,
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
  const [connectPromptServer, setConnectPromptServer] = useState<MCPServerEntry | null>(null);
  const [expandedToolsId, setExpandedToolsId] = useState<string | null>(null);
  const [bridgeServer, setBridgeServer] = useState<MCPServerEntry | null>(null);
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

  // Show the "connect first" prompt modal instead of directly opening the connect modal
  const promptConnectServerById = (serverId: string) => {
    const entry = serverById[serverId];
    if (entry) setConnectPromptServer(entry);
    else scrollToCatalog();
  };

  // Helper: get a fresh server-by-id map directly from the query cache
  // (avoids stale-closure bugs inside mutation onSuccess callbacks).
  const getFreshServerById = () => {
    const cached = queryClient.getQueryData<{ servers: MCPServerEntry[] }>(["catalog", accessToken, ""]);
    return Object.fromEntries((cached?.servers ?? []).map((s) => [s.id, s]));
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
      vendorApi.searchCatalogTools(accessToken, { q, top_k_servers: 5, top_k_tools: 8 }),
    onSuccess: (res) => {
      setSearchResult(res);
    },
  });

  // "Run": pick one tool + fill its arguments via LLM — still doesn't call it.
  const planMutation = useMutation({
    mutationFn: (q: string) =>
      vendorApi.planToolCall(accessToken, { q, top_k_servers: 5, top_k_tools: 8 }),
    onSuccess: (res) => {
      setPlanResult(res);
    },
  });

  const scrollToCatalog = () => {
    catalogSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

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
          <Button type="submit" disabled={searchMutation.isPending || !query.trim()}>
            {searchMutation.isPending ? <Spinner /> : <Sparkles className="h-4 w-4 mr-1" />}
            Compile
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handlePlan}
            disabled={planMutation.isPending || !query.trim()}
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
                    {s.auth_type === "device_pairing" ? (
                      <WhatsAppBridgeButtons
                        server={s}
                        accessToken={accessToken}
                        onOpenQr={() => setBridgeServer(s)}
                        onChanged={() => queryClient.invalidateQueries({ queryKey: ["catalog", accessToken] })}
                      />
                    ) : s.connected ? (
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
                {connectMutation.isPending && (connectMutation.variables as any)?.id === s.id && (
                  <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50/80 p-3 space-y-1.5">
                    <div className="flex items-center justify-between text-xs font-semibold text-sky-800">
                      <span className="flex items-center gap-1.5">
                        <Spinner className="h-3.5 w-3.5 text-sky-600" />
                        Connecting {s.name}...
                      </span>
                      <span className="text-[10px] font-mono text-sky-600 uppercase">Connecting</span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-sky-200">
                      <div className="h-full bg-gradient-to-r from-indigo-500 via-sky-500 to-emerald-500 animate-pulse rounded-full w-full" />
                    </div>
                    <p className="text-[11px] text-sky-700">Verifying credentials and synchronizing MCP tools...</p>
                  </div>
                )}
                {disconnectMutation.isPending && (disconnectMutation.variables as any) === s.id && (
                  <div className="mt-3 rounded-lg border border-red-200 bg-red-50/80 p-3 space-y-1.5">
                    <div className="flex items-center justify-between text-xs font-semibold text-red-800">
                      <span className="flex items-center gap-1.5">
                        <Spinner className="h-3.5 w-3.5 text-red-600" />
                        Disconnecting {s.name}...
                      </span>
                      <span className="text-[10px] font-mono text-red-600 uppercase">Disconnecting</span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-red-200">
                      <div className="h-full bg-gradient-to-r from-red-400 via-red-500 to-amber-500 animate-pulse rounded-full w-full" />
                    </div>
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
          accessToken={accessToken}
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
          onOAuthConnected={() => {
            queryClient.invalidateQueries({ queryKey: ["catalog", accessToken] });
            setConnectServer(null);
          }}
        />
      )}

      {connectPromptServer && (
        <ConnectServerPromptModal
          server={connectPromptServer}
          onClose={() => setConnectPromptServer(null)}
          onConnect={() => {
            setConnectPromptServer(null);
            setConnectServer(connectPromptServer);
          }}
        />
      )}

      {bridgeServer && (
        <WhatsAppBridgeModal
          server={bridgeServer}
          accessToken={accessToken}
          onClose={() => setBridgeServer(null)}
          onConnected={() => {
            queryClient.invalidateQueries({ queryKey: ["catalog", accessToken] });
            setBridgeServer(null);
          }}
        />
      )}
    </ProtectedDashboard>
  );
}

// ─── Connect-Server Prompt Modal ────────────────────────────────────────────
function ConnectServerPromptModal({
  server,
  onClose,
  onConnect,
}: {
  server: MCPServerEntry;
  onClose: () => void;
  onConnect: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-indigo-600 to-sky-500 px-6 py-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="rounded-full bg-white/20 p-2">
                <PlugZap className="h-5 w-5 text-white" />
              </div>
              <h3 className="text-base font-semibold text-white">Server not connected</h3>
            </div>
            <button
              onClick={onClose}
              className="rounded-full bg-white/10 p-1 text-white hover:bg-white/20 transition-colors cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          <p className="text-sm text-zinc-600">
            To use tools from{" "}
            <span className="font-semibold font-mono text-zinc-900">{server.name}</span>, you need
            to connect this server to your account first.
          </p>
          <div className="mt-4 rounded-xl border border-zinc-100 bg-zinc-50 p-3 flex items-center gap-3">
            <div className="rounded-full bg-sky-100 p-2">
              <Server className="h-4 w-4 text-sky-600" />
            </div>
            <div>
              <p className="text-xs font-semibold text-zinc-800 font-mono">{server.name}</p>
              <p className="text-xs text-zinc-400 mt-0.5">{server.description || "MCP server"}</p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 pb-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-50 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConnect}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-indigo-600 to-sky-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity cursor-pointer"
          >
            <Link2 className="h-4 w-4" />
            Connect {server.name}
          </button>
        </div>
      </div>
    </div>
  );
}

function UserConnectModal({
  server,
  accessToken,
  isPending,
  error,
  onClose,
  onSubmit,
  onOAuthConnected,
}: {
  server: MCPServerEntry;
  accessToken: string;
  isPending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (credentials?: Record<string, string> | null) => void;
  onOAuthConnected: () => void;
}) {
  const fields = server.credential_fields ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const isOAuth = server.auth_type === "oauth2";
  const [oauthMessage, setOauthMessage] = useState<string | null>(null);
  const isStdio = server.transport === "stdio";
  // No declared fields ever surfaced for this server (auth_type detection
  // said "none"/unknown) — for a non-stdio server that can still be wrong
  // (e.g. a real OAuth-less-looking endpoint that actually wants a bearer
  // token), so offer the same manual key/value override the vendor
  // admin's own Test Connection modal always has, instead of leaving the
  // end-user with no way to supply one at all.
  const needsNoCreds = fields.length === 0 && isStdio;
  const [credKey, setCredKey] = useState("");
  const [credValue, setCredValue] = useState("");

  // The provider redirects into a popup we open, which posts back here once
  // the user finishes (or cancels) their own consent screen — same
  // mechanism as the vendor admin's own OAuth connect (see
  // apps/backend/vendor/api/v1/router.py::_oauth_result_html and the
  // vendor tools page's identical listener).
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      const data = event.data;
      if (!data || (data.type !== "MCP_OAUTH_SUCCESS" && data.type !== "MCP_OAUTH_ERROR")) return;
      if (data.serverId && data.serverId !== server.id) return;
      if (data.type === "MCP_OAUTH_SUCCESS") {
        onOAuthConnected();
      } else {
        setOauthMessage(data.message || "Connection failed.");
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [server.id, onOAuthConnected]);

  const oauthAuthorizeMutation = useMutation({
    mutationFn: () => vendorApi.startMCPOAuthAuthorizeAsUser(accessToken, server.id, {}),
    onSuccess: (data) => {
      window.open(data.authorization_url, "mcp-oauth-connect-user", "width=600,height=750");
      setOauthMessage("Waiting for you to finish in the popup window…");
    },
    onError: (err) => {
      setOauthMessage(err instanceof ApiError ? err.message : "Could not start the OAuth flow.");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (fields.length > 0) {
      onSubmit(values);
    } else if (credKey && credValue) {
      onSubmit({ [credKey]: credValue });
    } else {
      onSubmit(null);
    }
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

        {isOAuth ? (
          <div className="mt-4 space-y-4">
            <p className="text-xs text-zinc-500">
              This connects <span className="font-mono">{server.name}</span> using your own
              account via OAuth — you&apos;ll sign in and consent in a popup window. Your
              resulting access token is stored separately from anyone else&apos;s.
            </p>

            {oauthMessage && <p className="text-xs text-indigo-600">{oauthMessage}</p>}
            {error && <p className="text-xs text-red-600">{error}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                type="button"
                disabled={oauthAuthorizeMutation.isPending}
                onClick={() => {
                  setOauthMessage(null);
                  oauthAuthorizeMutation.mutate();
                }}
              >
                {oauthAuthorizeMutation.isPending ? (
                  <>
                    <Spinner className="mr-1" /> Starting...
                  </>
                ) : (
                  <>
                    <Globe className="h-4 w-4 mr-1" /> Connect via OAuth
                  </>
                )}
              </Button>
            </div>
          </div>
        ) : (
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
          ) : needsNoCreds ? (
            <p className="rounded-md bg-zinc-50 p-3 text-xs text-zinc-500">
              No credentials required — click connect to verify access.
            </p>
          ) : (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-zinc-600">
                  Credential key (e.g. Authorization or API_KEY)
                </label>
                <Input value={credKey} onChange={(e) => setCredKey(e.target.value)} placeholder="Authorization" />
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-600">
                  Credential value (e.g. Bearer TOKEN or sk_test_...)
                </label>
                <Input
                  type="password"
                  value={credValue}
                  onChange={(e) => setCredValue(e.target.value)}
                  placeholder="Bearer ..."
                />
              </div>
              <p className="text-xs text-zinc-400">
                Leave blank if the server does not require authentication — this vendor didn&apos;t
                declare a specific credential, but you can supply one manually if you know it needs
                one.
              </p>
            </div>
          )}

          {error && <p className="text-xs text-red-600">{error}</p>}

          {isPending && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50/90 p-3.5 space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-indigo-900">
                <span className="flex items-center gap-2">
                  <Spinner className="h-4 w-4 text-indigo-600" />
                  Connecting {server.name}...
                </span>
                <span className="text-[10px] font-mono text-indigo-600 uppercase">Connecting</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-indigo-200">
                <div className="h-full bg-gradient-to-r from-indigo-500 via-sky-500 to-emerald-500 animate-pulse rounded-full w-full" />
              </div>
              <p className="text-xs text-indigo-700">Verifying credentials and discovering available tools...</p>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? (
                <>
                  <Spinner className="mr-1" /> Connecting...
                </>
              ) : (
                <>
                  <Link2 className="h-4 w-4 mr-1" /> Connect
                </>
              )}
            </Button>
          </div>
        </form>
        )}
      </div>
    </div>
  );
}

// Native device-pairing bridge (WhatsApp) button group — replaces the
// generic Connect/Connected/Disconnect buttons for any server whose
// auth_type is "device_pairing", since there's no credential to type in
// and disconnect vs. "forget this device" are genuinely different actions
// (see apps/backend/vendor/services/whatsapp_bridge/manager.py).
function WhatsAppBridgeButtons({
  server,
  accessToken,
  onOpenQr,
  onChanged,
}: {
  server: MCPServerEntry;
  accessToken: string;
  onOpenQr: () => void;
  onChanged: () => void;
}) {
  const disconnectMutation = useMutation({
    mutationFn: () => vendorApi.disconnectBridgeAsUser(accessToken, server.id),
    onSuccess: onChanged,
  });
  const forgetMutation = useMutation({
    mutationFn: () => vendorApi.forgetBridgeAsUser(accessToken, server.id),
    onSuccess: onChanged,
  });

  if (server.connected) {
    return (
      <>
        <button
          type="button"
          onClick={onOpenQr}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 cursor-pointer"
          title="View connection status"
        >
          <CheckCircle2 className="h-3 w-3" /> Connected
        </button>
        <button
          type="button"
          onClick={() => {
            if (confirm(`Disconnect "${server.name}"? Your phone stays linked — reconnecting won't need a new QR scan.`)) {
              disconnectMutation.mutate();
            }
          }}
          disabled={disconnectMutation.isPending}
          className="inline-flex items-center justify-center rounded-md border border-red-200 bg-red-50 p-1 text-red-600 hover:bg-red-100 disabled:opacity-50 cursor-pointer"
          title="Disconnect (keeps your phone linked)"
        >
          <Unlink className="h-3 w-3" />
        </button>
        <button
          type="button"
          onClick={() => {
            if (confirm(`Forget "${server.name}"? This unlinks your phone completely — you'll need to scan a new QR code to reconnect.`)) {
              forgetMutation.mutate();
            }
          }}
          disabled={forgetMutation.isPending}
          className="inline-flex items-center justify-center rounded-md border border-zinc-200 bg-zinc-50 p-1 text-zinc-500 hover:bg-zinc-100 disabled:opacity-50 cursor-pointer"
          title="Forget this device (requires a new QR scan next time)"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </>
    );
  }

  return (
    <button
      type="button"
      onClick={onOpenQr}
      className="inline-flex items-center gap-1 rounded-md border border-sky-200 bg-sky-50 px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 cursor-pointer"
    >
      <QrCode className="h-3 w-3" /> Connect
    </button>
  );
}

// Starts this user's own bridge process and polls its status, showing the
// real QR code (as text — the bridge's ASCII-art QR is itself a genuine
// scannable QR code when rendered in a monospace font, same as running it
// in a terminal) once available.
function WhatsAppBridgeModal({
  server,
  accessToken,
  onClose,
  onConnected,
}: {
  server: MCPServerEntry;
  accessToken: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [status, setStatus] = useState<BridgeStatus | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const poll = async () => {
    try {
      const s = await vendorApi.getBridgeStatusAsUser(accessToken, server.id);
      setStatus(s);
      if (s.status === "connected") {
        stopPolling();
        onConnected();
      } else if (s.status === "error") {
        stopPolling();
      }
    } catch {
      // Transient network hiccup while polling — next tick retries.
    }
  };

  const startMutation = useMutation({
    mutationFn: () => vendorApi.startBridgeAsUser(accessToken, server.id),
    onSuccess: (s) => {
      setStatus(s);
      if (s.status !== "connected" && s.status !== "error") {
        pollRef.current = setInterval(poll, 2000);
      }
    },
    onError: (err) => {
      setStartError(err instanceof ApiError ? err.message : "Could not start the WhatsApp bridge.");
    },
  });

  useEffect(() => {
    startMutation.mutate();
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [server.id]);

  const isConnecting = status?.status === "starting" || (!status && startMutation.isPending);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Connect &quot;{server.name}&quot;</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-4 space-y-4 text-center">
          {startError && <p className="text-xs text-red-600">{startError}</p>}

          {isConnecting && (
            <div className="flex flex-col items-center gap-2 py-6">
              <Spinner className="h-6 w-6 text-emerald-600" />
              <p className="text-xs text-zinc-500">Starting your WhatsApp bridge…</p>
            </div>
          )}

          {status?.status === "awaiting_qr" && status.qr && (
            <>
              <p className="text-xs text-zinc-500">
                Open WhatsApp on your phone → Settings → Linked Devices → Link a Device, then
                scan this code.
              </p>
              <pre className="mx-auto w-fit overflow-auto rounded-md bg-white p-2 text-[6px] leading-[6px] tracking-tighter">
                {status.qr}
              </pre>
              <p className="text-[11px] text-zinc-400">Waiting for you to scan…</p>
            </>
          )}

          {status?.status === "connected" && (
            <div className="flex flex-col items-center gap-2 py-6 text-emerald-700">
              <CheckCircle2 className="h-8 w-8" />
              <p className="text-sm font-medium">Connected!</p>
            </div>
          )}

          {status?.status === "error" && (
            <div className="space-y-3">
              <p className="text-xs text-red-600">{status.error || "Connection failed."}</p>
              <Button
                type="button"
                onClick={() => {
                  setStatus(null);
                  startMutation.mutate();
                }}
              >
                Try again
              </Button>
            </div>
          )}
        </div>
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
