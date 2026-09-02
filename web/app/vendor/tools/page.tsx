"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Server,
  Plus,
  Trash2,
  Share2,
  X,
  Globe,
  Lock,
  Radio,
  Link,
  Check,
  Search,
  Globe as GlobeIcon,
} from "lucide-react";

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
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/auth-fields";

export default function VendorMCPPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const [showAddModal, setShowAddModal] = useState(false);
  const [showAnalyzeModal, setShowAnalyzeModal] = useState(false);
  const [showGrantModal, setShowGrantModal] = useState(false);
  const [showToolsModal, setShowToolsModal] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [analyzeRepoUrl, setAnalyzeRepoUrl] = useState("");
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

  // Queries
  const { data: servers = [], isLoading } = useQuery({
    queryKey: ["vendor-mcp-servers", accessToken],
    queryFn: () => vendorApi.listMCPServers(accessToken),
    enabled: !!accessToken,
  });

  const { data: tenants = [] }: { data: VendorTenant[] | undefined } = useQuery({
    queryKey: ["vendor-tenants", accessToken],
    queryFn: () => api.getVendorTenants(accessToken),
    enabled: !!accessToken,
  });

  // Analyze repo mutation
  const analyzeRepoMutation = useMutation({
    mutationFn: (repoUrl: string) => vendorApi.analyzeRepo(accessToken, repoUrl),
    onSuccess: (data) => {
      setAnalyzeResult(data);
      setIsAnalyzing(false);
    },
    onError: (err) => {
      setAnalyzeResult(null);
      setIsAnalyzing(false);
    },
  });

  const handleAnalyzeRepo = (url: string) => {
    if (!url || !url.trim()) return;
    setAnalyzeRepoUrl(url.trim());
    setIsAnalyzing(true);
    setAnalyzeResult(null);
    analyzeRepoMutation.mutate(url.trim());
  };

  // Resource & Server Management Mutations
  const createMutation = useMutation({
    mutationFn: (vals: ConnectMCPServerBody) => vendorApi.createMCPServer(accessToken, vals),
    onSuccess: () => {
      setShowAddModal(false);
      queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => vendorApi.deleteMCPServer(accessToken, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] }),
  });

  const embedMutation = useMutation({
    mutationFn: (id: string) => vendorApi.embedMCPServer(accessToken, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] }),
  });

  const connectMutation = useMutation({
    mutationFn: ({ id, credentials }: { id: string; credentials?: Record<string, string> | null }) =>
      vendorApi.connectMCPServer(accessToken, id, credentials),
    onSuccess: (data, vars) => {
      const id = (vars as any).id as string;
      setToolsServer({ id, name: servers.find((s) => s.id === id)?.name ?? id, response: data, error: null });
      setShowToolsModal(true);
    },
    onError: (err, vars) => {
      const id = (vars as any).id as string;
      setToolsServer({
        id,
        name: servers.find((s) => s.id === id)?.name ?? id,
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
    onSuccess: () => setShowGrantModal(false),
  });

  return (
    <ProtectedDashboard
      path="/vendor"
      title="MCP Servers"
      description="Register MCP servers, embed them for semantic matching, and grant access to tenants."
    >
      <div className="mt-6 flex items-center justify-between">
        <a href="/vendor" className="text-sm text-zinc-500 hover:text-zinc-800 cursor-pointer">
          ← Back to dashboard
        </a>
        <Button onClick={() => setShowAddModal(true)} size="sm">
          <Plus className="h-4 w-4 mr-1" /> Register MCP Server
        </Button>
      </div>

      <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
        <div className="flex items-center gap-2 border-b border-zinc-100 pb-4">
          <Server className="h-5 w-5 text-indigo-600" />
          <div>
            <h2 className="text-lg font-semibold text-zinc-900">Registered MCP Servers</h2>
            <p className="text-sm text-zinc-500">
              Servers are embedded on create (best-effort) for the AI Compiler&apos;s semantic matcher.
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-6 w-6 text-zinc-500" />
          </div>
        ) : servers.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-400">
            No MCP servers registered yet — click &ldquo;Register MCP Server&rdquo;.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm text-zinc-600">
              <thead className="bg-zinc-50 text-xs font-semibold uppercase text-zinc-500">
                <tr>
                  <th className="px-4 py-3">Server</th>
                  <th className="px-4 py-3">Transport</th>
                  <th className="px-4 py-3">Scope</th>
                  <th className="px-4 py-3">URL</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {servers.map((s) => (
                  <tr key={s.id} className="hover:bg-zinc-50/50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-900">{s.name}</div>
                      <div className="text-xs text-zinc-400">{s.description || "—"}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-700">
                        {s.transport}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {s.is_global ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                          <Globe className="h-3 w-3" /> Global
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                          <Lock className="h-3 w-3" /> Granted
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-500">
                      {s.server_url || <span className="text-zinc-400">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => {
                            setConnectServer(s);
                            setCredKey("");
                            setCredValue("");
                            setShowConnectModal(true);
                          }}
                          className="p-1 text-zinc-400 hover:text-emerald-600 cursor-pointer"
                          title="Test connection & discover tools"
                          disabled={connectMutation.isPending}
                        >
                          <Link className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => embedMutation.mutate(s.id)}
                          className="p-1 text-zinc-400 hover:text-indigo-600 cursor-pointer"
                          title="(Re)compute semantic embedding"
                          disabled={embedMutation.isPending}
                        >
                          <Radio className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            setGrantServer(s);
                            setShowGrantModal(true);
                          }}
                          className="p-1 text-zinc-400 hover:text-sky-600 cursor-pointer"
                          title="Grant to tenant"
                        >
                          <Share2 className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Delete server "${s.name}"? This revokes any tenant grants.`)) {
                              deleteMutation.mutate(s.id);
                            }
                          }}
                          className="p-1 text-zinc-400 hover:text-red-600 cursor-pointer"
                          title="Delete server"
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

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

      {showConnectModal && connectServer && (
        <ConnectCredentialModal
          server={connectServer}
          onClose={() => setShowConnectModal(false)}
          onSubmit={() => {
            const creds = credKey && credValue ? { [credKey]: credValue } : undefined;
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

function CreateMCPModal({
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  onClose: () => void;
  onSubmit: (vals: ConnectMCPServerBody) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [isGlobal, setIsGlobal] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return;
    if (!serverUrl.trim()) return;
    onSubmit({
      name,
      description,
      server_url: serverUrl,
      is_global: isGlobal,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Register MCP Server</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <p className="mt-1 text-xs text-zinc-500">
          Transport and tools are auto-discovered on connect.
        </p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Server name">
            <Input
              placeholder="finance.invoice-server"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </Field>
          <Field label="Description">
            <Input
              placeholder="Connect to the invoice MCP server."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <Field label="Server URL">
            <Input
              placeholder="https://mcp.example.com/invoice"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              required
            />
          </Field>
          <label className="flex items-center gap-2 text-sm text-zinc-700">
            <input
              type="checkbox"
              checked={isGlobal}
              onChange={(e) => setIsGlobal(e.target.checked)}
              className="h-4 w-4 rounded border-zinc-300"
            />
            Global (available to all solo users without a tenant grant)
          </label>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : <Plus className="h-4 w-4 mr-1" />} Register
            </Button>
          </div>
        </form>
      </div>
    </div>
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
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">
            Tools for &ldquo;{serverName}&rdquo;
          </h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        {isPending ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-6 w-6 text-zinc-500" />
          </div>
        ) : error ? (
          <div className="py-4">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        ) : response ? (
          <div className="py-4 space-y-3">
            <div className="flex items-center gap-2 text-sm text-zinc-600">
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
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                    {tool}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-zinc-400">No tools discovered.</p>
            )}
          </div>
        ) : null}

        <div className="flex justify-end pt-4">
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
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
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
              className="flex h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm focus-visible:ring-2 focus-visible:ring-zinc-900"
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
  onClose,
  onSubmit,
  credKey,
  credValue,
  setCredKey,
  setCredValue,
  isPending,
}: {
  server: VendorMCPServer;
  onClose: () => void;
  onSubmit: () => void;
  credKey: string;
  credValue: string;
  setCredKey: (v: string) => void;
  setCredValue: (v: string) => void;
  isPending: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Connect to "{server.name}"</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit();
          }}
          className="mt-4 space-y-4"
        >
          <Field label="Credential key (e.g. Authorization)">
            <Input value={credKey} onChange={(e) => setCredKey(e.target.value)} placeholder="Authorization" />
          </Field>
          <Field label="Credential value (e.g. Bearer TOKEN)">
            <Input value={credValue} onChange={(e) => setCredValue(e.target.value)} placeholder="Bearer ..." />
          </Field>

          <p className="text-xs text-zinc-500">Leave blank to attempt anonymous connect.</p>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={isPending}>{isPending ? <Spinner /> : <Link className="h-4 w-4 mr-1" />} Connect</Button>
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
  const [isGlobal, setIsGlobal] = useState(false);
  const [envVars, setEnvVars] = useState<Record<string, string>>({});

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

    onRegister({
      name: serverName.trim(),
      description,
      server_url: targetUrl,
      is_global: isGlobal,
      source_repo_url: activeTab === "github" ? urlInput.trim() : undefined,
      env_vars: envVars,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Register MCP Server</h3>
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
          // Analysis Results Report Card & Registration Form
          <form onSubmit={handleRegister} className="mt-4 space-y-4">
            <div className="p-3 bg-indigo-50/50 rounded-lg border border-indigo-100 space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-indigo-900">
                <span>Analysis Complete</span>
                <span className="capitalize px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">
                  {analyzeResult.transport} ({analyzeResult.runtime})
                </span>
              </div>
              {analyzeResult.suggested_command && (
                <p className="text-xs font-mono bg-white p-2 rounded border border-indigo-100 text-zinc-800">
                  {analyzeResult.suggested_command}
                </p>
              )}
              {analyzeResult.remote_endpoint && (
                <p className="text-xs font-mono bg-white p-2 rounded border border-indigo-100 text-zinc-800">
                  {analyzeResult.remote_endpoint}
                </p>
              )}
            </div>

            <Field label="Server Name">
              <Input
                placeholder="e.g. GitHub MCP Server"
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

            {analyzeResult.required_env_vars.length > 0 && (
              <div className="space-y-2">
                <label className="text-xs font-medium text-zinc-700">Required Environment Secrets</label>
                {analyzeResult.required_env_vars.map((key) => (
                  <Field key={key} label={key}>
                    <Input
                      type="password"
                      placeholder={`Enter ${key}`}
                      value={envVars[key] || ""}
                      onChange={(e) => setEnvVars({ ...envVars, [key]: e.target.value })}
                    />
                  </Field>
                ))}
              </div>
            )}

            <label className="flex items-center gap-2 text-sm text-zinc-700">
              <input
                type="checkbox"
                checked={isGlobal}
                onChange={(e) => setIsGlobal(e.target.checked)}
                className="h-4 w-4 rounded border-zinc-300"
              />
              Global (available to all solo users without tenant grant)
            </label>

            {error && <p className="text-xs text-red-600">{error}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={isRegistering}>
                {isRegistering ? <Spinner /> : <Plus className="h-4 w-4 mr-1" />} Register & Discover Tools
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
                placeholder="https://github.com/github/github-mcp-server"
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