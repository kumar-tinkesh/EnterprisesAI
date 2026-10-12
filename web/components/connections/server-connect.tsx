"use client";

/**
 * Connecting the current user's own account to an MCP server: credentials or
 * OAuth (UserConnectModal) and the WhatsApp device-pairing bridge. Used by
 * the AI Compiler's Connections view and by the guided agent setup.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Globe, Link2, QrCode, Trash2, Unlink, X } from "lucide-react";

import { vendorApi, ApiError, type MCPServerEntry, type BridgeStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

export function UserConnectModal({
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
export function WhatsAppBridgeButtons({
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
export function WhatsAppBridgeModal({
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

/**
 * Connect one server by id, from anywhere (the guided agent setup): finds it
 * in the user's catalog and opens the right dialog for it. Rendered into
 * <body> so it keeps the light theme (the WhatsApp QR must stay dark-on-light
 * to scan) even when opened from the dark builder.
 */
export function ConnectServerDialog({
  serverId,
  token,
  onClose,
  onConnected,
}: {
  serverId: string;
  token: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const queryClient = useQueryClient();
  const catalog = useQuery({ queryKey: ["catalog", token, ""], queryFn: () => vendorApi.getCatalog(token), enabled: !!token });
  const server = catalog.data?.servers.find((s) => s.id === serverId);

  const done = () => {
    void queryClient.invalidateQueries({ queryKey: ["catalog", token] });
    void queryClient.invalidateQueries({ queryKey: ["builder-server-tools", serverId] });
    void queryClient.invalidateQueries({ queryKey: ["builder-tool-search"] });
    onConnected();
  };
  const connect = useMutation({
    mutationFn: (credentials?: Record<string, string> | null) => vendorApi.connectMCPServerAsUser(token, serverId, credentials),
    onSuccess: done,
  });

  if (typeof document === "undefined") return null;
  let dialog: React.ReactNode;
  if (server?.auth_type === "device_pairing") {
    dialog = <WhatsAppBridgeModal server={server} accessToken={token} onClose={onClose} onConnected={done} />;
  } else if (server) {
    dialog = (
      <UserConnectModal
        server={server}
        accessToken={token}
        isPending={connect.isPending}
        error={connect.isError ? (connect.error instanceof ApiError ? connect.error.message : "Connection failed") : null}
        onClose={onClose}
        onSubmit={(credentials) => connect.mutate(credentials)}
        onOAuthConnected={done}
      />
    );
  } else {
    dialog = (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4" role="dialog" aria-modal="true">
        <div className="w-full max-w-sm rounded-xl bg-white p-6 text-center shadow-xl">
          {catalog.isLoading ? (
            <Spinner className="mx-auto h-6 w-6 text-zinc-500" />
          ) : (
            <>
              <p className="text-sm text-zinc-700">
                {catalog.isError ? "Couldn't load your servers." : "This server isn't available to you any more. Ask your admin to grant it again."}
              </p>
              <Button className="mt-4" variant="outline" onClick={onClose}>Close</Button>
            </>
          )}
        </div>
      </div>
    );
  }
  return createPortal(dialog, document.body);
}
