"use client";

/**
 * The vendor admin's setup for "Connect with Instagram" (backend vendor/api/v1/oauth.py::set_instagram_sign_in):
 * the Meta app's ID and secret and its Instagram login configuration, and the callback URL to register there.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Copy, ExternalLink, X } from "lucide-react";

import { vendorApi, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

/** True for the thenavidm/instagram-mcp server, before or after its profile is applied. */
export function isInstagramServer(s: { auth_type?: string | null; source_repo_url?: string | null; server_url?: string | null }) {
  return s.auth_type === "instagram_meta" || [s.source_repo_url, s.server_url].some((u) => (u || "").toLowerCase().includes("thenavidm/instagram-mcp"));
}

export function InstagramSignInModal({ serverId, serverName, accessToken, onClose }: { serverId: string; serverName: string; accessToken: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const key = ["instagram-sign-in", serverId];
  const setup = useQuery({ queryKey: key, queryFn: () => vendorApi.getInstagramSignIn(accessToken, serverId), enabled: !!accessToken });
  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [configId, setConfigId] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!setup.data) return;
    setAppId(setup.data.app_id ?? "");
    setConfigId(setup.data.config_id ?? "");
  }, [setup.data]);

  const save = useMutation({
    mutationFn: () => vendorApi.setInstagramSignIn(accessToken, serverId, { app_id: appId.trim(), config_id: configId.trim(), ...(secret.trim() ? { app_secret: secret.trim() } : {}) }),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data);
      void queryClient.invalidateQueries({ queryKey: ["vendor-mcp-servers"] });
      setSecret("");
      setError(null);
      setSaved(true);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Couldn't save."),
  });

  const d = setup.data;
  const needsSecret = !d?.has_secret && !secret.trim();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-xs">
      <div className="max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-xl border border-zinc-200 bg-[var(--surface-raised)] p-5 shadow-xl sm:p-6">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Connect with Instagram: {serverName}</h3>
          <button type="button" aria-label="Close" onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        {setup.isLoading ? (
          <div className="flex justify-center py-10"><Spinner className="h-5 w-5 text-zinc-400" /></div>
        ) : setup.isError ? (
          <p className="mt-4 text-sm text-red-600">{setup.error instanceof Error ? setup.error.message : "Couldn't load the setup."}</p>
        ) : d ? (
          <form
            className="mt-4 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <p className={d.ready ? "flex items-center gap-1.5 text-sm text-emerald-700" : "text-sm text-zinc-600"}>
              {d.ready ? <><CheckCircle2 className="h-4 w-4" /> On: people see &ldquo;Connect with Instagram&rdquo; on their Connectors page.</> : "Off: people can only paste a token. Add your Meta app to turn the button on."}
            </p>

            <ol className="list-decimal space-y-1.5 rounded-md bg-zinc-50 p-3 pl-7 text-xs text-zinc-700">
              <li>In your Meta app open <b>Use cases → Instagram API → Configure your app</b> and select the Instagram-compatible configuration. Copy its <b>Configuration ID</b>.</li>
              <li>Add the <b>Redirect URL</b> below to that configuration, and save it there.</li>
              <li>From <b>App settings → Basic</b>, copy the <b>App ID</b> and <b>App secret</b>.</li>
              <li>Until App Review, only people with a role on the app (Instagram testers) can finish signing in.</li>
            </ol>

            <div>
              <p className="text-xs font-medium text-zinc-600">Redirect URL</p>
              <div className="mt-1 flex gap-2">
                <code className="min-w-0 flex-1 truncate rounded-md border border-zinc-200 bg-zinc-50 px-2 py-2 font-mono text-xs text-zinc-800" title={d.redirect_uri}>{d.redirect_uri}</code>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-9 shrink-0"
                  onClick={() => {
                    void navigator.clipboard.writeText(d.redirect_uri).then(() => {
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    });
                  }}
                >
                  <Copy className="h-3.5 w-3.5" /> {copied ? "Copied" : "Copy"}
                </Button>
              </div>
              {!d.redirect_is_https && (
                <p className="mt-1.5 flex gap-1.5 text-xs text-amber-800">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  Meta only accepts https. Run the app on a public https address (e.g. ngrok) and set BACKEND_PUBLIC_URL to it, then register the new URL.
                </p>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="ig-app-id" className="block text-xs font-medium text-zinc-600">App ID</label>
                <Input id="ig-app-id" inputMode="numeric" value={appId} onChange={(e) => setAppId(e.target.value)} placeholder="2973…" />
              </div>
              <div>
                <label htmlFor="ig-config-id" className="block text-xs font-medium text-zinc-600">Configuration ID</label>
                <Input id="ig-config-id" inputMode="numeric" value={configId} onChange={(e) => setConfigId(e.target.value)} placeholder="1155…" />
              </div>
            </div>
            <div>
              <label htmlFor="ig-secret" className="block text-xs font-medium text-zinc-600">App secret</label>
              <Input id="ig-secret" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={d.has_secret ? "Saved, leave empty to keep it" : "From App settings → Basic"} />
              <p className="mt-1 text-xs text-zinc-500">Stored encrypted; never shown again or sent to anyone&apos;s browser.</p>
            </div>

            <a href="https://developers.facebook.com/apps/" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-indigo-700 hover:underline">
              Open your Meta apps <ExternalLink className="h-3 w-3" />
            </a>

            {error && <p className="text-xs text-red-600">{error}</p>}
            {saved && !error && <p className="text-xs text-emerald-700">Saved.</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onClose}>Close</Button>
              <Button type="submit" disabled={save.isPending || !appId.trim() || !configId.trim() || needsSecret}>
                {save.isPending ? <Spinner className="h-4 w-4" /> : null} Save
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </div>
  );
}
