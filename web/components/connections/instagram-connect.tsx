"use client";

/**
 * Connecting your own Instagram (backend vendor/services/mcp_auth/instagram.py): "Connect with Instagram"
 * when the admin has set up the Meta app — a Meta sign-in in a popup, nothing to copy — and always a
 * pasted token as the other way, with the steps and the permissions to tick when making one.
 */

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckSquare, ChevronDown, ExternalLink, Link2, Square } from "lucide-react";

import { vendorApi, ApiError, type MCPServerEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const TOKEN = "IG_ACCESS_TOKEN";
const USER_ID = "IG_USER_ID";

/** What a token made on Meta for this needs, and what each one is for. */
const PERMISSIONS: [string, string][] = [
  ["instagram_basic", "profile and posts"],
  ["instagram_manage_insights", "reach, views, and other accounts' public profiles"],
  ["instagram_manage_comments", "read and reply to comments"],
  ["instagram_content_publish", "post photos, reels and stories"],
  ["instagram_manage_messages", "read and answer DMs"],
  ["pages_show_list", "find the account through its Page"],
  ["pages_read_engagement", "read through the Page"],
];

/** Mirrors the backend's check (instagram.token_problem), so a wrong paste is caught before Connect. */
function tokenProblem(raw: string): string | null {
  const t = raw.trim().replace(/^["']|["']$/g, "").replace(/^bearer\s*/i, "").replace(/\s+/g, "");
  if (!t) return null;
  if (t.startsWith("AQ") || t.includes("code=")) return "That looks like the one-time code from a sign-in, not an access token.";
  if (t.length < 60) return "That's too short for an access token. Copy the whole token.";
  if (!/^[A-Za-z0-9_\-|.]+$/.test(t)) return "The token has characters a token never has. Copy it again.";
  return null;
}

export function InstagramConnect({
  server,
  accessToken,
  isPending,
  error,
  onClose,
  onSubmit,
}: {
  server: MCPServerEntry;
  accessToken: string;
  isPending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (credentials: Record<string, string>) => void;
}) {
  const canSignIn = server.sign_in === "instagram";
  const [pasteOpen, setPasteOpen] = useState(!canSignIn);
  const [token, setToken] = useState("");
  const [userId, setUserId] = useState("");
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<{ tone: "info" | "ok" | "error"; text: string } | null>(null);
  const problem = tokenProblem(token);

  // The popup posts back (vendor/api/v1/oauth.py::_oauth_result_html); the parent modal refreshes the list.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const data = event.data;
      if (!data || (data.type !== "MCP_OAUTH_SUCCESS" && data.type !== "MCP_OAUTH_ERROR")) return;
      if (data.serverId && data.serverId !== server.id) return;
      setMessage({ tone: data.type === "MCP_OAUTH_SUCCESS" ? "ok" : "error", text: data.message || "Connection failed." });
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [server.id]);

  const signIn = useMutation({
    mutationFn: () => vendorApi.startInstagramSignIn(accessToken, server.id),
    onSuccess: (data) => {
      window.open(data.authorization_url, "instagram-connect", "width=600,height=760");
      setMessage({ tone: "info", text: "Finish in the popup: sign in with Instagram or Facebook and pick your account." });
    },
    onError: (err) => setMessage({ tone: "error", text: err instanceof ApiError ? err.message : "Couldn't start the sign-in." }),
  });

  const tick = (p: string) =>
    setTicked((cur) => {
      const next = new Set(cur);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });

  return (
    <div className="mt-4 space-y-4">
      <p className="text-xs text-zinc-500">
        Connects your own Instagram professional account (Business or Creator). It&apos;s stored separately from anyone else&apos;s.
      </p>

      {canSignIn ? (
        <div className="space-y-2">
          <Button
            type="button"
            className="h-11 w-full bg-gradient-to-r from-[#f58529] via-[#dd2a7b] to-[#8134af] text-white hover:opacity-90"
            disabled={signIn.isPending}
            onClick={() => {
              setMessage(null);
              signIn.mutate();
            }}
          >
            {signIn.isPending ? <Spinner className="h-4 w-4" /> : <InstagramGlyph />} Connect with Instagram
          </Button>
          <p className="text-center text-xs text-zinc-500">Sign in, allow access, and you&apos;re connected. Nothing to copy.</p>
        </div>
      ) : (
        <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-900">
          &ldquo;Connect with Instagram&rdquo; isn&apos;t turned on yet; ask your admin. Until then, paste a token below.
        </p>
      )}

      {message && (
        <p className={cn("text-xs", message.tone === "ok" ? "text-emerald-700" : message.tone === "error" ? "text-red-600" : "text-indigo-600")}>{message.text}</p>
      )}

      {/* The other way: a token made on Meta */}
      <div className="rounded-lg border border-zinc-200">
        <button
          type="button"
          onClick={() => setPasteOpen((o) => !o)}
          aria-expanded={pasteOpen}
          className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-medium text-zinc-800 cursor-pointer"
        >
          {canSignIn ? "Or paste a token instead" : "Paste a token"}
          <ChevronDown className={cn("ml-auto h-4 w-4 text-zinc-500 transition-transform", pasteOpen && "rotate-180")} />
        </button>
        {pasteOpen && (
          <form
            className="space-y-4 border-t border-zinc-200 p-3"
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit({ [TOKEN]: token, [USER_ID]: userId });
            }}
          >
            <details className="group rounded-md bg-zinc-50 p-3 text-xs text-zinc-700">
              <summary className="cursor-pointer font-medium text-zinc-900">Don&apos;t have a token? How to make one (5 min)</summary>
              <ol className="mt-2 list-decimal space-y-1.5 pl-4">
                <li>In the Instagram app: Settings → Account type and tools → switch to a <b>professional</b> account (Business or Creator). It&apos;s free.</li>
                <li>
                  Open Meta Business settings → Users → <b>System users</b>, pick or add one, and under <b>Assign assets</b> give it your Instagram account
                  (and the app).
                </li>
                <li>Press <b>Generate new token</b>, pick the app, set expiry to <b>Never</b>, and tick these permissions:</li>
              </ol>
              <ul className="mt-2 space-y-1">
                {PERMISSIONS.map(([p, why]) => (
                  <li key={p}>
                    <button type="button" onClick={() => tick(p)} className="flex w-full items-start gap-2 text-left cursor-pointer" aria-pressed={ticked.has(p)}>
                      {ticked.has(p) ? <CheckSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" /> : <Square className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" />}
                      <span>
                        <code className="font-mono text-zinc-900">{p}</code> <span className="text-zinc-500">· {why}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-zinc-500">Tick them here as you tick them on Meta; only what you pick there counts.</p>
              <ol start={4} className="mt-2 list-decimal space-y-1.5 pl-4">
                <li>Copy the token (it starts with <code className="font-mono">EAA</code>). Check it in the Access Token Debugger if you like: Valid should say True.</li>
                <li>Your Instagram account ID (17841…) is on the Meta app&apos;s Instagram API page, next to your account.</li>
              </ol>
              <div className="mt-2 flex flex-wrap gap-3">
                <a href="https://business.facebook.com/settings/system-users" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-indigo-700 hover:underline">
                  Meta Business settings <ExternalLink className="h-3 w-3" />
                </a>
                <a href="https://developers.facebook.com/tools/debug/accesstoken/" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-indigo-700 hover:underline">
                  Access Token Debugger <ExternalLink className="h-3 w-3" />
                </a>
              </div>
              <p className="mt-2 text-zinc-500">Never paste the token anywhere else, like a chat.</p>
            </details>

            <div>
              <label htmlFor="ig-token" className="block text-xs font-medium text-zinc-600">Access token (starts with EAA or IG)</label>
              <Input id="ig-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="EAA…" />
              {problem && <p className="mt-1 text-xs text-red-600">{problem}</p>}
            </div>
            <div>
              <label htmlFor="ig-user" className="block text-xs font-medium text-zinc-600">Instagram account ID (numbers only)</label>
              <Input id="ig-user" inputMode="numeric" autoComplete="off" value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="17841…" />
              {userId && /\D/.test(userId.trim()) && <p className="mt-1 text-xs text-amber-700">Only the numbers are used.</p>}
            </div>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onClose} disabled={isPending}>Cancel</Button>
              <Button type="submit" disabled={isPending || !token.trim() || !userId.trim() || !!problem}>
                {isPending ? <Spinner className="h-4 w-4" /> : <Link2 className="h-4 w-4" />} Connect
              </Button>
            </div>
          </form>
        )}
      </div>

      {!pasteOpen && (
        <div className="flex justify-end">
          <Button type="button" variant="outline" onClick={onClose}>Close</Button>
        </div>
      )}
    </div>
  );
}

function InstagramGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}
