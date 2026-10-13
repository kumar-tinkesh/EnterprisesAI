"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  ArrowLeft,
  Search,
  Server,
  Wrench,
  Link2,
  Unlink,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import { vendorApi, ApiError, type MCPServerEntry } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { AgentEditor } from "@/components/builder/agent-editor";
import { WorkflowEditor } from "@/components/builder/workflow-editor";
import { editorHref, type BuildTarget } from "@/lib/builder/use-builder-actions";
import { UserConnectModal, WhatsAppBridgeButtons, WhatsAppBridgeModal } from "@/components/connections/server-connect";
import { AgentWizardHost } from "@/components/builder/agent-wizard/agent-wizard";
import { useAgentWizard } from "@/stores/agent-wizard-store";
import BuilderHome from "./agent-canvas";

/** ?agent=<id> / ?workflow=<id> -> the agent or workflow open in the editor. */
function targetFromUrl(): BuildTarget | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const agent = params.get("agent");
  const workflow = params.get("workflow");
  return workflow ? { kind: "workflow", id: workflow } : agent ? { kind: "agent", id: agent } : null;
}

export default function UserAgentsPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [view, setView] = useState<"canvas" | "connections">("canvas");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [connectServer, setConnectServer] = useState<MCPServerEntry | null>(null);
  const [expandedToolsId, setExpandedToolsId] = useState<string | null>(null);
  const [bridgeServer, setBridgeServer] = useState<MCPServerEntry | null>(null);

  // An agent or workflow open in place of the canvas — built here, or opened
  // from Executions. Kept in the URL so reload / the back button behave.
  const [editing, setEditing] = useState<BuildTarget | null>(null);
  useEffect(() => {
    const target = targetFromUrl();
    // A saved wizard left open (it lives in sessionStorage) would cover the
    // editor this link asked for; it's done, so close it.
    if (target && useAgentWizard.getState().createdId) useAgentWizard.getState().close();
    setEditing(target);
    const onPop = () => setEditing(targetFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const openEditor = (target: BuildTarget) => {
    window.history.pushState(null, "", editorHref(target));
    setEditing(target);
  };
  const closeEditor = () => {
    window.history.pushState(null, "", "/user/agents");
    setEditing(null);
    setView("canvas");
  };

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

  if (editing) {
    return (
      <ProtectedDashboard path="/user" title="AI Compiler" description="Build and test an agent or workflow" fullBleed>
        {editing.kind === "workflow" ? (
          <WorkflowEditor key={editing.id} id={editing.id} onBack={closeEditor} onOpen={openEditor} onSwitch={(workflowId) => openEditor({ kind: "workflow", id: workflowId })} />
        ) : (
          <AgentEditor key={editing.id} id={editing.id} onBack={closeEditor} onOpen={openEditor} />
        )}
        <AgentWizardHost onOpen={openEditor} />
      </ProtectedDashboard>
    );
  }

  return (
    <ProtectedDashboard
      path="/user"
      title="AI Compiler"
      description="Connect the MCP servers your agents and workflows use."
      fullBleed={view === "canvas"}
    >
      {view === "canvas" && (
        <BuilderHome hasAnyConnectedServer={hasAnyConnectedServer} onConnections={() => setView("connections")} onOpen={openEditor} />
      )}

      {view === "connections" && (
        <>
          <div className="mt-6">
            <button
              type="button"
              onClick={() => setView("canvas")}
              className="inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-800 cursor-pointer"
            >
              <ArrowLeft className="h-4 w-4" /> Back to canvas
            </button>
          </div>

          {/* Authorized catalog */}
          <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
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
        </>
      )}

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

      <AgentWizardHost onOpen={openEditor} />

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
