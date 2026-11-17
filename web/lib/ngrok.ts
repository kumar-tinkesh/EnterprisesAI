"use client";

/**
 * ngrok's free plan answers a browser's request with its own "You are about to visit…" page instead of
 * passing it on, unless the request carries `ngrok-skip-browser-warning`. Opening the site still shows that
 * page once (a page load can't carry a header), but the app's own API calls must never get it: they'd
 * read HTML where JSON was expected, and sign-in would stop halfway.
 *
 * So when the app was built for an ngrok domain (docker-compose.ngrok.yml), every fetch to that domain gets
 * the header. Built for localhost, nothing changes.
 */

const NGROK_HOST = /\.(ngrok-free\.app|ngrok-free\.dev|ngrok\.app|ngrok\.dev|ngrok\.io)$/i;

function apiHost(): string | null {
  const url = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_BACKEND_API_URL || "";
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

let installed = false;

export function installNgrokHeader() {
  if (installed || typeof window === "undefined") return;
  const host = apiHost();
  if (!host || !NGROK_HOST.test(host.split(":")[0])) return;
  installed = true;

  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    let target: string;
    try {
      target = new URL(url, window.location.href).host;
    } catch {
      return original(input, init);
    }
    if (target !== host) return original(input, init);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    headers.set("ngrok-skip-browser-warning", "1");
    return original(input, { ...init, headers });
  };
}

installNgrokHeader();
