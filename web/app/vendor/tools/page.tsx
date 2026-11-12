"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Server,
  Plus,
  Share2,
  X,
  Globe,
  Lock,
  Radio,
  Link,
  CheckCircle2,
  Check,
  Search,
  Globe as GlobeIcon,
  ChevronRight,
} from "lucide-react";
import { InstagramSignInModal } from "@/components/connections/instagram-sign-in-admin";
import { ConnectorIcon } from "@/components/connections/connector-icon";
import { appLabel } from "@/lib/connectors";
import { AppPanel, STATE_LOOK, appState, type AppState } from "./app-panel";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import { api, ApiError, type VendorTenant } from "@/lib/api";
import {
  vendorApi,
  type VendorMCPServer,
  type ConnectMCPServerBody,
  type ConnectMCPServerResponse,
  type AnalyzeRepoResponse,
  type AnalyzeRepoRequest,
  type OAuthConfigBody,
  type OAuthAuthorizeBody,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/auth-fields";

export default function VendorMCPPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const [showAddModal, setShowAddModal] = useState(false);
  const [showGrantModal, setShowGrantModal] = useState(false);
  const [showToolsModal, setShowToolsModal] = useState(false);
  const [igServer, setIgServer] = useState<{ id: string; name: string } | null>(null);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeRepoResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [grantServer, setGrantServer] = useState<VendorMCPServer | null>(null);
  const [toolsServer, setToolsServer] = useState<{
    id: string;
    name: string;
    response: ConnectMCPServerResponse | null;
    error: string | null;
  } | null>(null);
  const [connectServer, setConnectServer] = useState<VendorMCPServer | null>(null);
  const [credKey, setCredKey] = useState("");
  const [credValue, setCredValue] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "attention" | "ready" | "restricted">("all");

  // Queries
  const { data: servers = [], isLoading, isError: listFailed, refetch: retryList } = useQuery({
    queryKey: ["vendor-mcp-servers", accessToken],
    queryFn: () => vendorApi.listMCPServers(accessToken),
    enabled: !!accessToken,
  });
  const overview = useQuery({
    queryKey: ["vendor-mcp-overview", accessToken],
    queryFn: () => vendorApi.mcpOverview(accessToken),
    enabled: !!accessToken,
  });
  const counts = new Map((overview.data ?? []).map((c) => [c.id, c]));

  const { data: tenants = [] }: { data: VendorTenant[] | undefined } = useQuery({
    queryKey: ["vendor-tenants", accessToken],
    queryFn: () => api.getVendorTenants(accessToken),
    enabled: !!accessToken,
  });

  const analyzeRepoMutation = useMutation({
    mutationFn: (repoUrl: string) => vendorApi.analyzeRepo(accessToken, repoUrl),
    onSuccess: (data) => {
      setAnalyzeResult(data);
      setIsAnalyzing(false);
    },
    onError: () => {
      setAnalyzeResult(null);
      setIsAnalyzing(false);
    },
  });

  const handleAnalyzeRepo = (url: string) => {
    if (!url || !url.trim()) return;
    setIsAnalyzing(true);
    setAnalyzeResult(null);
    analyzeRepoMutation.mutate(url.trim());
  };

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] });
    queryClient.invalidateQueries({ queryKey: ["vendor-mcp-overview"] });
  };

  const createMutation = useMutation({
    mutationFn: (vals: ConnectMCPServerBody) => vendorApi.createMCPServer(accessToken, vals),
    onSuccess: (created) => {
      setShowAddModal(false);
      setAnalyzeResult(null);
      refreshAll();
      // Straight to the new app, whose next step is its first test.
      if (created?.id) setOpenId(created.id);
    },
  });

  const connectMutation = useMutation({
    mutationFn: ({ id, credentials }: { id: string; credentials?: Record<string, string> | null }) =>
      vendorApi.connectMCPServer(accessToken, id, credentials),
    onSuccess: (data, vars) => {
      setToolsServer({ id: vars.id, name: servers.find((s) => s.id === vars.id)?.name ?? vars.id, response: data, error: null });
      setShowToolsModal(true);
      refreshAll();
      queryClient.invalidateQueries({ queryKey: ["vendor-mcp-details", vars.id] });
    },
    onError: (err, vars) => {
      setToolsServer({
        id: vars.id,
        name: servers.find((s) => s.id === vars.id)?.name ?? vars.id,
        response: null,
        error: err instanceof ApiError ? err.message : "Connection failed",
      });
      setShowToolsModal(true);
    },
  });

  const grantMutation = useMutation({
    mutationFn: (vals: { tenant_id: string; resource_id: string }) =>
      vendorApi.grantResource(accessToken, {
        tenant_id: vals.tenant_id,
        resource_type: "mcp",
        resource_id: vals.resource_id,
      }),
    onSuccess: (_d, vals) => {
      setShowGrantModal(false);
      refreshAll();
      queryClient.invalidateQueries({ queryKey: ["vendor-mcp-details", vals.resource_id] });
    },
  });

  const testingId = connectMutation.isPending ? connectMutation.variables?.id : undefined;
  const openTest = (s: VendorMCPServer) => {
    setConnectServer(s);
    setCredKey("");
    setCredValue("");
    setShowConnectModal(true);
  };

  const q = search.trim().toLowerCase();
  // Two apps with one title ("News" twice) get their own name added.
  const titles = new Map<string, number>();
  for (const s of servers) titles.set(appLabel(s.name, s.description).title, (titles.get(appLabel(s.name, s.description).title) ?? 0) + 1);
  const labelOf = (s: VendorMCPServer) => {
    const l = appLabel(s.name, s.description);
    return (titles.get(l.title) ?? 0) > 1 ? { ...l, title: `${l.title} (${s.name})` } : l;
  };
  const rows = servers
    .map((s) => ({ s, state: appState(s, testingId === s.id), label: labelOf(s) }))
    .filter(({ s, label }) => !q || [s.name, label.title, label.blurb, s.description, s.server_url, s.source_repo_url].some((x) => (x || "").toLowerCase().includes(q)));
  const needsYou = (state: AppState) => state === "not_tested" || state === "no_tools";
  const FILTERS = [
    ["all", "All", rows.length],
    ["attention", "Needs attention", rows.filter((r) => needsYou(r.state)).length],
    ["ready", "Ready", rows.filter((r) => r.state === "ready").length],
    ["restricted", "Restricted", rows.filter((r) => !r.s.is_global).length],
  ] as const;
  const shown = rows
    .filter(({ s, state }) =>
      filter === "attention" ? needsYou(state) : filter === "ready" ? state === "ready" : filter === "restricted" ? !s.is_global : true,
    )
    // What needs the admin first, then by name.
    .sort((a, b) => Number(needsYou(b.state)) - Number(needsYou(a.state)) || a.label.title.localeCompare(b.label.title));
  const open = servers.find((s) => s.id === openId) ?? null;

  return (
    <ProtectedDashboard
      path="/vendor"
      title="Apps"
      description="The MCP servers people can connect: add them, test them, and choose who can use them."
      action={
        <Button onClick={() => setShowAddModal(true)} size="sm" className="h-9">
          <Plus className="h-4 w-4" /> Add app
        </Button>
      }
    >
      <div className="mt-6 space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input aria-label="Search apps" className="h-9 pl-8" placeholder="Search apps" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter">
            {FILTERS.map(([id, text, n]) => (
              <button
                key={id}
                type="button"
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
                className={
                  "rounded-full border px-3 py-1 text-xs font-medium cursor-pointer " +
                  (filter === id ? "border-[var(--accent)] bg-[var(--accent)] text-white" : "border-zinc-200 text-zinc-600 hover:bg-zinc-50")
                }
              >
                {text} <span className="tabular-nums opacity-75">{n}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-zinc-200">
          {isLoading ? (
            <div className="flex justify-center py-10">
              <Spinner className="h-6 w-6 text-zinc-500" />
            </div>
          ) : listFailed ? (
            <div className="px-6 py-10 text-center">
              <p className="text-sm text-zinc-700">Couldn&apos;t load the apps. The server may be restarting.</p>
              <Button className="mt-3" size="sm" variant="outline" onClick={() => void retryList()}>Try again</Button>
            </div>
          ) : servers.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <Server className="mx-auto h-8 w-8 text-zinc-400" />
              <p className="mt-2 text-sm font-medium text-zinc-900">No apps yet</p>
              <p className="mt-1 text-sm text-zinc-500">Add one from a GitHub repo or a server URL.</p>
              <Button className="mt-4" size="sm" onClick={() => setShowAddModal(true)}>
                <Plus className="h-4 w-4" /> Add app
              </Button>
            </div>
          ) : shown.length === 0 ? (
            <p className="px-6 py-10 text-center text-sm text-zinc-500">Nothing matches. Try another search or filter.</p>
          ) : (
            <ul className="divide-y divide-zinc-100">
              {shown.map(({ s, state, label }) => {
                const c = counts.get(s.id);
                const look = STATE_LOOK[state];
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => setOpenId(s.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-zinc-50 cursor-pointer"
                    >
                      <ConnectorIcon name={s.name} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-zinc-900">{label.title}</span>
                          {!s.is_global && <Lock className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="Restricted" />}
                        </span>
                        <span className="block truncate text-xs text-zinc-500">
                          {label.blurb || s.description || s.server_url}
                        </span>
                      </span>
                      <span className="hidden shrink-0 text-right text-xs text-zinc-500 md:block">
                        <span className="block tabular-nums">{s.bound_tools?.length ?? 0} tools</span>
                        <span className="block tabular-nums">{c ? `${c.users_connected} connected` : ""}</span>
                      </span>
                      <span className={"inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium " + look.className}>
                        {state === "testing" ? <Spinner className="h-3 w-3" /> : state === "ready" ? <CheckCircle2 className="h-3 w-3" /> : null}
                        <span className="hidden sm:inline">{look.label}</span>
                      </span>
                      <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {open && (
        <AppPanel
          server={open}
          title={labelOf(open).title}
          counts={counts.get(open.id)}
          accessToken={accessToken}
          testing={testingId === open.id}
          onTest={() => openTest(open)}
          onInstagram={() => setIgServer({ id: open.id, name: open.name })}
          onGrant={() => {
            setGrantServer(open);
            setShowGrantModal(true);
          }}
          onClose={() => setOpenId(null)}
        />
      )}

      {showAddModal && (
        <AnalyzeRepoModal
          onClose={() => setShowAddModal(false)}
          onAnalyze={handleAnalyzeRepo}
          onRegister={(vals) => createMutation.mutate(vals)}
          isAnalyzing={isAnalyzing}
          isRegistering={createMutation.isPending}
          analyzeResult={analyzeResult}
          error={
            analyzeRepoMutation.isError
              ? analyzeRepoMutation.error instanceof ApiError
                ? analyzeRepoMutation.error.message
                : "Failed to analyze repository"
              : createMutation.isError
              ? createMutation.error instanceof ApiError
                ? createMutation.error.message
                : "Failed to register MCP server"
              : null
          }
        />
      )}

      {showGrantModal && grantServer && (
        <GrantServerModal
          server={grantServer}
          tenants={tenants}
          onClose={() => setShowGrantModal(false)}
          onSubmit={(vals) =>
            grantMutation.mutate({ tenant_id: vals.tenant_id, resource_id: grantServer.id })
          }
          isPending={grantMutation.isPending}
          error={
            grantMutation.isError
              ? grantMutation.error instanceof ApiError
                ? grantMutation.error.message
                : "Failed to grant resource"
              : null
          }
        />
      )}

      {showToolsModal && toolsServer && (
        <ToolsModal
          serverName={toolsServer.name}
          response={toolsServer.response}
          error={toolsServer.error}
          isPending={connectMutation.isPending}
          onClose={() => setShowToolsModal(false)}
        />
      )}

      {igServer && (
        <InstagramSignInModal serverId={igServer.id} serverName={igServer.name} accessToken={accessToken} onClose={() => setIgServer(null)} />
      )}

      {showConnectModal && connectServer && (
        <ConnectCredentialModal
          // Look the server up fresh from the list each render — the OAuth
          // "Set endpoints"/"Connect via OAuth" actions invalidate this
          // query, but connectServer itself is a snapshot taken when the
          // modal opened and would otherwise never pick up the update.
          server={servers.find((s) => s.id === connectServer.id) ?? connectServer}
          accessToken={accessToken}
          onClose={() => setShowConnectModal(false)}
          onSubmit={(creds) => {
            connectMutation.mutate({ id: connectServer.id, credentials: creds ?? null });
            setShowConnectModal(false);
          }}
          credKey={credKey}
          credValue={credValue}
          setCredKey={setCredKey}
          setCredValue={setCredValue}
          isPending={connectMutation.isPending}
        />
      )}
    </ProtectedDashboard>
  );
}

function ToolsModal({
  serverName,
  response,
  error,
  isPending,
  onClose,
}: {
  serverName: string;
  response: ConnectMCPServerResponse | null;
  error: string | null;
  isPending: boolean;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="flex max-h-[85vh] w-full max-w-md flex-col rounded-xl bg-[var(--surface-raised)] shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 px-6 py-4">
          <h3 className="text-lg font-semibold text-zinc-900">
            Tools for &ldquo;{serverName}&rdquo;
          </h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {isPending ? (
            <div className="flex justify-center py-8">
              <Spinner className="h-6 w-6 text-zinc-500" />
            </div>
          ) : error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : response ? (
            <div className="space-y-3">
              <div className="sticky -top-4 flex items-center gap-2 bg-[var(--surface-raised)] pb-2 pt-1 text-sm text-zinc-600">
                <span className="inline-flex items-center rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium">
                  {response.transport}
                </span>
                <span className="text-xs text-zinc-500">
                  {response.bound_tools.length} tool(s) discovered
                </span>
              </div>
              {response.bound_tools.length > 0 ? (
                <ul className="space-y-1">
                  {response.bound_tools.map((tool) => (
                    <li key={tool} className="flex items-center gap-2 text-sm text-zinc-700">
                      <Check className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                      {tool}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-zinc-400">No tools discovered.</p>
              )}
            </div>
          ) : null}
        </div>

        <div className="flex justify-end border-t border-zinc-100 px-6 py-4">
          <Button variant="outline" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  );
}

function GrantServerModal({
  server,
  tenants,
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  server: VendorMCPServer;
  tenants: VendorTenant[];
  onClose: () => void;
  onSubmit: (vals: { tenant_id: string }) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [tenantId, setTenantId] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!tenantId) return;
    onSubmit({ tenant_id: tenantId });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-[var(--surface-raised)] p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">
            Grant &ldquo;{server.name}&rdquo; to tenant
          </h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Tenant / Organization">
            <select
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              required
              className="flex h-10 w-full rounded-md border border-zinc-300 bg-[var(--surface-raised)] px-3 text-sm focus-visible:ring-2 focus-visible:ring-zinc-900"
            >
              <option value="" disabled>Select a tenant…</option>
              {tenants
                .filter((t) => !t.is_personal)
                .map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
            </select>
          </Field>
          <p className="text-xs text-zinc-500">
            All members of this tenant will inherit access to this MCP server.
          </p>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : <Share2 className="h-4 w-4 mr-1" />} Grant access
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ConnectCredentialModal({
  server,
  accessToken,
  onClose,
  onSubmit,
  credKey,
  credValue,
  setCredKey,
  setCredValue,
  isPending,
}: {
  server: VendorMCPServer;
  accessToken: string;
  onClose: () => void;
  onSubmit: (creds?: Record<string, string>) => void;
  credKey: string;
  credValue: string;
  setCredKey: (v: string) => void;
  setCredValue: (v: string) => void;
  isPending: boolean;
}) {
  const queryClient = useQueryClient();
  const [customCreds, setCustomCreds] = useState<Record<string, string>>({});
  // Credential fields come from two sources:
  //  1. auth_config.credential_fields — populated by MCP detection for remote
  //     servers (entries are {name, label, type, ...} objects).
  //  2. env_vars — stdio servers are not probeable, so their required keys
  //     surface as the env vars captured at registration.
  // An EMPTY detected list must fall through to env_vars, hence the length
  // check instead of `||` (an empty array is truthy in JS and would block
  // the fallback). Env keys that already have a stored value are injected
  // automatically at connect time, so only the empty ones are asked for.
  const labelsMap: Record<string, string> = {};
  if (Array.isArray((server.auth_config as any)?.credential_fields)) {
    for (const f of (server.auth_config as any).credential_fields as any[]) {
      if (f && typeof f === "object" && f.name) {
        labelsMap[f.name] = f.label || f.name;
      }
    }
  }

  const detectedFields: string[] = Array.isArray(
    (server.auth_config as any)?.credential_fields
  )
    ? ((server.auth_config as any).credential_fields as any[])
        .map((f) => (typeof f === "string" ? f : f?.name))
        .filter(Boolean)
    : [];
  const envFields: string[] = server.env_vars
    ? Object.keys(server.env_vars).filter(
        (k) => !server.env_vars?.[k] // skip keys with a stored value
      )
    : [];
  const credentialFields: string[] =
    detectedFields.length > 0 ? detectedFields : envFields;
  const isStdio = server.transport === "stdio";
  const needsNoCreds = credentialFields.length === 0 && isStdio;
  // device_pairing (e.g. WhatsApp): there is no vendor-wide account to
  // verify here — the test below runs our vendored MCP server with no
  // bridge, which discovers its tools; each user then pairs their own phone
  // by QR before those tools can run. Read from auth_config directly
  // (not the top-level auth_type) so this can't silently go stale again
  // the way it did before (see the c8e2a6f13d90 backfill migration).
  const isDevicePairing = (server.auth_config as any)?.auth_type === "device_pairing";

  // ── OAuth "Connect via provider" bootstrap (see oauth_flow.py backend) ──
  const isOAuth = server.auth_type === "oauth2";
  const oauthCfg: { authorization_endpoint?: string; token_endpoint?: string; registration_endpoint?: string } =
    (server.auth_config as any)?.oauth || {};
  const oauthConfigured = !!(oauthCfg.authorization_endpoint && oauthCfg.token_endpoint);
  // The server registers our client itself (RFC 7591): no OAuth app to fill in.
  const oauthSelfRegisters = !!(oauthCfg.authorization_endpoint && oauthCfg.registration_endpoint);

  const [showOAuthConfig, setShowOAuthConfig] = useState(false);
  const [authEndpoint, setAuthEndpoint] = useState("");
  const [tokenEndpoint, setTokenEndpoint] = useState("");
  const [oauthScope, setOauthScope] = useState("");
  const [oauthMessage, setOauthMessage] = useState<string | null>(null);

  // The provider redirects into a popup we open, which posts back here once
  // the admin finishes (or cancels) the consent screen — see
  // apps/backend/vendor/api/v1/router.py::_oauth_result_html.
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      const data = event.data;
      if (!data || (data.type !== "MCP_OAUTH_SUCCESS" && data.type !== "MCP_OAUTH_ERROR")) return;
      if (data.serverId && data.serverId !== server.id) return;
      setOauthMessage(data.message || (data.type === "MCP_OAUTH_SUCCESS" ? "Connected." : "Failed."));
      if (data.type === "MCP_OAUTH_SUCCESS") {
        queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] });
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [server.id, queryClient]);

  const oauthConfigMutation = useMutation({
    mutationFn: (body: OAuthConfigBody) => vendorApi.setMCPOAuthConfig(accessToken, server.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] });
      setShowOAuthConfig(false);
    },
  });

  const oauthAuthorizeMutation = useMutation({
    mutationFn: (body: OAuthAuthorizeBody) => vendorApi.startMCPOAuthAuthorize(accessToken, server.id, body),
    onSuccess: (data) => {
      window.open(data.authorization_url, "mcp-oauth-connect", "width=600,height=750");
      setOauthMessage("Waiting for you to finish in the popup window…");
    },
    onError: (err) => {
      setOauthMessage(err instanceof ApiError ? err.message : "Could not start the OAuth flow.");
    },
  });

  // Client ID/secret are just normal detected fields (e.g. QUICKBOOKS_CLIENT_ID) —
  // find them by suffix rather than assuming an exact name, same fuzzy-match
  // spirit as the backend's callback-param matching.
  const findCredBySuffix = (suffix: string): string => {
    const key = Object.keys(customCreds).find((k) => k.toUpperCase().endsWith(suffix));
    return key ? customCreds[key] : "";
  };

  const handleOAuthConnect = () => {
    const clientId = findCredBySuffix("CLIENT_ID");
    const clientSecret = findCredBySuffix("CLIENT_SECRET");
    if (oauthSelfRegisters && !(clientId && clientSecret)) {
      setOauthMessage(null);
      oauthAuthorizeMutation.mutate({});
      return;
    }
    if (!clientId || !clientSecret) {
      setOauthMessage("Fill in the Client ID and Client Secret fields above first.");
      return;
    }
    setOauthMessage(null);
    oauthAuthorizeMutation.mutate({ client_id: clientId, client_secret: clientSecret });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (needsNoCreds) {
      onSubmit(undefined);
    } else if (credentialFields.length > 0 && Object.keys(customCreds).length > 0) {
      onSubmit(customCreds);
    } else if (credKey && credValue) {
      onSubmit({ [credKey]: credValue });
    } else {
      onSubmit(undefined);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-[var(--surface-raised)] p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Test Connection: "{server.name}"</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          {isDevicePairing ? (
            <div className="rounded-lg bg-amber-50 border border-amber-200 p-3">
              <p className="text-xs font-medium text-amber-900">
                No credentials needed — each user pairs their own phone.
              </p>
              <p className="mt-1 text-xs text-amber-700">
                Testing discovers this server&apos;s tools and makes it available to users.
                Each user then connects from their own dashboard by scanning a QR code with
                their phone; until they do, the tools can&apos;t run for them.
              </p>
            </div>
          ) : needsNoCreds ? (
            <div className="rounded-lg bg-emerald-50 border border-emerald-100 p-3">
              <p className="text-xs font-medium text-emerald-800">
                No credentials required.
              </p>
              <p className="mt-1 text-xs text-emerald-600">
                This stdio server authenticates at runtime (e.g. via a local token or QR
                flow) and none were detected at registration. Click below to connect and
                discover tools.
              </p>
            </div>
          ) : (
            <p className="text-xs text-zinc-500">
              Enter required credentials to test connection and discover available tools. Credentials will be encrypted and stored in the secure vault.
            </p>
          )}

          {(server.auth_config as any)?.auth_type === "linkedin_cookie" && (
            <p className="rounded-lg bg-sky-50 border border-sky-100 p-3 text-xs text-sky-800">
              Paste a LinkedIn <span className="font-mono">li_at</span> cookie to test it: sign in to linkedin.com,
              open DevTools → Application → Cookies → https://www.linkedin.com and copy the value of li_at. Each
              user still connects their own cookie; runs always use the runner&apos;s.
            </p>
          )}

          {credentialFields.length > 0 ? (
            <div className="space-y-3">
              <label className="text-xs font-semibold text-zinc-700">
                Required Credentials{isStdio && (server.auth_config as any)?.auth_type !== "linkedin_cookie" ? " (passed as environment variables)" : ""}
              </label>
              {credentialFields.map((field) => (
                <Field key={field} label={labelsMap[field] || field}>
                  <Input
                    type="password"
                    placeholder={`Enter ${labelsMap[field] || field}`}
                    value={customCreds[field] || ""}
                    onChange={(e) => setCustomCreds({ ...customCreds, [field]: e.target.value })}
                  />
                </Field>
              ))}
            </div>
          ) : !needsNoCreds ? (
            <>
              <Field label="Credential key (e.g. Authorization or API_KEY)">
                <Input
                  value={credKey}
                  onChange={(e) => setCredKey(e.target.value)}
                  placeholder="Authorization"
                />
              </Field>
              <Field label="Credential value (e.g. Bearer TOKEN or sk_test_...)">
                <Input
                  type="password"
                  value={credValue}
                  onChange={(e) => setCredValue(e.target.value)}
                  placeholder="Bearer ..."
                />
              </Field>
              <p className="text-xs text-zinc-400">
                Leave blank if the server does not require authentication.
                {isStdio
                  ? " For stdio servers use the environment variable name as the key (e.g. the token variable the server's README documents) — it will be injected into the server process."
                  : ""}
              </p>
            </>
          ) : null}

          {isOAuth && (
            <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-3 space-y-2">
              <p className="text-xs font-semibold text-indigo-800">OAuth provider detected</p>
              {!oauthConfigured ? (
                showOAuthConfig ? (
                  <div className="space-y-2">
                    <p className="text-xs text-indigo-600">
                      This server&apos;s authorize/token URLs weren&apos;t auto-detected (common for
                      local servers). Most providers publish these as fixed, documented URLs.
                    </p>
                    <Field label="Authorization endpoint">
                      <Input
                        value={authEndpoint}
                        onChange={(e) => setAuthEndpoint(e.target.value)}
                        placeholder="https://appcenter.intuit.com/connect/oauth2"
                      />
                    </Field>
                    <Field label="Token endpoint">
                      <Input
                        value={tokenEndpoint}
                        onChange={(e) => setTokenEndpoint(e.target.value)}
                        placeholder="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
                      />
                    </Field>
                    <Field label="Scope (optional)">
                      <Input
                        value={oauthScope}
                        onChange={(e) => setOauthScope(e.target.value)}
                        placeholder="com.intuit.quickbooks.accounting"
                      />
                    </Field>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        disabled={oauthConfigMutation.isPending || !authEndpoint.trim() || !tokenEndpoint.trim()}
                        onClick={() =>
                          oauthConfigMutation.mutate({
                            authorization_endpoint: authEndpoint.trim(),
                            token_endpoint: tokenEndpoint.trim(),
                            scope: oauthScope.trim() || undefined,
                          })
                        }
                      >
                        {oauthConfigMutation.isPending ? <Spinner /> : null} Save endpoints
                      </Button>
                      <Button type="button" size="sm" variant="outline" onClick={() => setShowOAuthConfig(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs text-indigo-700">
                      No authorize/token URL set yet for this provider.
                    </p>
                    <Button type="button" size="sm" variant="outline" onClick={() => setShowOAuthConfig(true)}>
                      Set OAuth endpoints
                    </Button>
                  </div>
                )
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-indigo-700">
                    {oauthSelfRegisters
                      ? "Sign in on the provider's consent screen — no OAuth app needed, it registers itself."
                      : "Fill in Client ID/Secret above, then connect via the provider's consent screen — it fills in the rest (refresh token, etc.) automatically."}
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    disabled={oauthAuthorizeMutation.isPending}
                    onClick={handleOAuthConnect}
                  >
                    {oauthAuthorizeMutation.isPending ? <Spinner /> : <GlobeIcon className="h-4 w-4 mr-1" />}
                    Connect via OAuth
                  </Button>
                </div>
              )}
              {oauthMessage && <p className="text-xs text-indigo-600">{oauthMessage}</p>}
            </div>
          )}

          {isPending && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50/90 p-3.5 space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-indigo-900">
                <span className="flex items-center gap-2">
                  <Spinner className="h-4 w-4 text-indigo-600" />
                  Testing connection & discovering tools...
                </span>
                <span className="text-xs font-mono text-indigo-600 uppercase">Connecting</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-indigo-200">
                <div className="h-full bg-gradient-to-r from-indigo-500 via-sky-500 to-emerald-500 animate-pulse rounded-full w-full" />
              </div>
              <p className="text-xs text-indigo-700">Running MCP protocol handshake and discovering tools list...</p>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={isPending}>Cancel</Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? (
                <>
                  <Spinner className="mr-1" />
                  {isDevicePairing ? "Checking..." : "Connecting..."}
                </>
              ) : (
                <>
                  <Link className="h-4 w-4 mr-1" />
                  {isDevicePairing ? "Check Server Reachability" : "Test Connection & Discover Tools"}
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function AnalyzeRepoModal({
  onClose,
  onAnalyze,
  onRegister,
  isAnalyzing,
  isRegistering,
  analyzeResult,
  error,
}: {
  onClose: () => void;
  onAnalyze: (url: string) => void;
  onRegister: (vals: ConnectMCPServerBody) => void;
  isAnalyzing: boolean;
  isRegistering: boolean;
  analyzeResult: AnalyzeRepoResponse | null;
  error: string | null;
}) {
  const [urlInput, setUrlInput] = useState("");
  const [activeTab, setActiveTab] = useState<"remote" | "github">("github");
  const [serverName, setServerName] = useState("");
  const [description, setDescription] = useState("");
  const [isGlobal, setIsGlobal] = useState(true);

  const handleAnalyze = (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlInput.trim()) return;
    onAnalyze(urlInput.trim());
  };

  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    if (!serverName.trim()) return;
    const targetUrl =
      analyzeResult?.remote_endpoint ||
      analyzeResult?.suggested_command ||
      urlInput.trim();

    const detectedEnvVars = analyzeResult?.required_env_vars?.length
      ? Object.fromEntries(analyzeResult.required_env_vars.map((k) => [k, ""]))
      : undefined;

    onRegister({
      name: serverName.trim(),
      description,
      server_url: targetUrl,
      is_global: isGlobal,
      source_repo_url: activeTab === "github" ? urlInput.trim() : undefined,
      env_vars: detectedEnvVars,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-lg rounded-xl bg-[var(--surface-raised)] p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Add app</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-4 border-b border-zinc-100">
          <nav className="flex gap-4" aria-label="Tabs">
            <button
              type="button"
              onClick={() => setActiveTab("remote")}
              className={`py-2 px-1 border-b-2 font-medium text-sm flex items-center gap-1.5 cursor-pointer ${
                activeTab === "remote"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-zinc-500 hover:text-zinc-700"
              }`}
            >
              <Globe className="h-4 w-4" /> Remote MCP Endpoint
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("github")}
              className={`py-2 px-1 border-b-2 font-medium text-sm flex items-center gap-1.5 cursor-pointer ${
                activeTab === "github"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-zinc-500 hover:text-zinc-700"
              }`}
            >
              <Server className="h-4 w-4" /> GitHub Repository URL
            </button>
          </nav>
        </div>

        {analyzeResult ? (
          // Analysis Results Report Card & Simple Registration Form
          <form onSubmit={handleRegister} className="mt-4 space-y-4">
            <div className="p-3 bg-indigo-50/50 rounded-lg border border-indigo-100 space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-indigo-900">
                <span>Analysis Complete</span>
                <span className="capitalize px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">
                  {analyzeResult.transport} ({analyzeResult.runtime})
                </span>
              </div>
              {analyzeResult.suggested_command && (
                <p className="text-xs font-mono bg-[var(--surface-raised)] p-2 rounded border border-indigo-100 text-zinc-800">
                  {analyzeResult.suggested_command}
                </p>
              )}
              {analyzeResult.remote_endpoint && (
                <p className="text-xs font-mono bg-[var(--surface-raised)] p-2 rounded border border-indigo-100 text-zinc-800">
                  {analyzeResult.remote_endpoint}
                </p>
              )}
              {analyzeResult.required_env_vars.length > 0 && (
                <p className="text-xs text-indigo-700 font-medium pt-1">
                  Detected Credentials needed: {analyzeResult.required_env_vars.join(", ")} (Prompted on Test Connection)
                </p>
              )}
            </div>

            <Field label="Server Name">
              <Input
                placeholder="e.g. My MCP Server"
                value={serverName}
                onChange={(e) => setServerName(e.target.value)}
                required
              />
            </Field>

            <Field label="Description">
              <Input
                placeholder="Optional description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>

            <label className="flex items-center gap-2 text-sm text-zinc-700">
              <input
                type="checkbox"
                checked={isGlobal}
                onChange={(e) => setIsGlobal(e.target.checked)}
                className="h-4 w-4 rounded border-zinc-300"
              />
              Available to all users (untick to show it only to tenants you grant it to)
            </label>

            {error && <p className="text-xs text-red-600">{error}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={isRegistering}>
                {isRegistering ? <Spinner /> : <Plus className="h-4 w-4 mr-1" />} Register MCP Server
              </Button>
            </div>
          </form>
        ) : activeTab === "remote" ? (
          // Remote MCP Endpoint Form
          <form onSubmit={handleAnalyze} className="mt-4 space-y-4">
            <Field label="Remote MCP Endpoint URL">
              <Input
                placeholder="https://mcp.example.com/sse"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                required
              />
            </Field>
            <p className="text-xs text-zinc-500">
              Enter a live MCP endpoint URL (HTTP/SSE). We&apos;ll probe it to detect transport & auth requirement.
            </p>

            {error && <p className="text-xs text-red-600">{error}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={isAnalyzing}>
                {isAnalyzing ? <Spinner /> : <Radio className="h-4 w-4 mr-1" />} Analyze Endpoint
              </Button>
            </div>
          </form>
        ) : (
          // GitHub Repo URL Form
          <form onSubmit={handleAnalyze} className="mt-4 space-y-4">
            <Field label="GitHub Repository URL">
              <Input
                placeholder="https://github.com/org/mcp-server"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                required
              />
            </Field>
            <p className="text-xs text-zinc-500">
              Enter a GitHub repo URL. We&apos;ll analyze its manifest, Dockerfile, and README to auto-detect transport, runtime, and required environment variables.
            </p>

            {error && <p className="text-xs text-red-600">{error}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={isAnalyzing}>
                {isAnalyzing ? <Spinner /> : <Server className="h-4 w-4 mr-1" />} Analyze Repository
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}