"use client";

import { Puzzle } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Brand marks for the connectors we know, as inline SVG (nothing fetched from
 * an icon CDN, so a card never flashes blank and the list never leaks out).
 * Connectors are matched by name, since servers here are named by the admin;
 * anything unknown gets a puzzle piece. Marks from the AI Marketplace.
 */
const ICONS: Record<string, React.ReactNode> = {
  slack: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <rect x="3" y="3" width="7.5" height="7.5" rx="2" fill="#36C5F0" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="2" fill="#2EB67D" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" fill="#ECB22E" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="2" fill="#E01E5A" />
    </svg>
  ),
  notion: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <rect width="24" height="24" rx="5" fill="#fff" />
      <path d="M6.5 18V6h2.1l7 8.6V6h2v12h-2.1l-7-8.6V18z" fill="#111" />
    </svg>
  ),
  github: (
    <svg viewBox="0 0 24 24" className="h-full w-full" fill="currentColor" aria-hidden>
      <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
  ),
  jira: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <path d="M12 2.5l9.2 9.2h-4.2L12 6.7l-5 5H2.8z" fill="#2684FF" />
      <path d="M12 10.5l9.2 9.2h-4.2L12 14.7l-5 5H2.8z" fill="#2684FF" opacity="0.55" />
    </svg>
  ),
  atlassian: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden fill="none">
      <path d="M11.057 5.257a1.57 1.57 0 0 1 1.539.015l4.621 2.668c.484.279.783.797.783 1.354v5.336a1.56 1.56 0 0 1-.782 1.355l-3.474 2.005a2 2 0 0 0 .12-.691v-5.337c0-.733-.39-1.409-1.026-1.774l-2.59-1.495V6.626q.001-.246.074-.473c.117-.364.366-.68.707-.877z" fill="#0052CC" />
      <path d="M9.881 5.94 6.408 7.945A1.56 1.56 0 0 0 5.625 9.3v5.337c0 .557.3 1.075.783 1.354l4.621 2.668c.475.274 1.06.279 1.539.015l.027-.019a1.57 1.57 0 0 0 .781-1.35v-2.067l-2.589-1.495a2.05 2.05 0 0 1-1.026-1.775V6.631a2 2 0 0 1 .12-.691" fill="#2684FF" />
    </svg>
  ),
  linear: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <rect width="24" height="24" rx="6" fill="#5E6AD2" />
      <g stroke="#fff" strokeWidth="1.6" strokeLinecap="round">
        <path d="M7 8.5l8 8" />
        <path d="M7 12.5l4 4" />
        <path d="M11 8.5l4.5 4.5" />
        <path d="M15 8.5l1 1" />
      </g>
    </svg>
  ),
  gmail: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <rect x="2" y="5" width="20" height="14" rx="2.5" fill="#fff" stroke="#EA4335" strokeWidth="1.6" />
      <path d="M3.2 7.2L12 13l8.8-5.8" fill="none" stroke="#EA4335" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  ),
  google_sheets: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <path fill="#0F9D58" d="M14.5 1H6a2 2 0 0 0-2 2v18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6.5z" />
      <path fill="#87CEAC" d="M14.5 1v5.5H20z" />
      <path fill="#fff" d="M7.5 10.5h9v7.5h-9zm1.5 1.5v1.5h2.5V12zm4 0v1.5H15V12zm-4 3v1.5h2.5V15zm4 0v1.5H15V15z" />
    </svg>
  ),
  quickbooks_pro: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <circle cx="12" cy="12" r="10" fill="#2CA01C" />
      <path d="M12 6.8a5.2 5.2 0 1 0 3.4 9.1l1.4 1.4 1.3-1.3-1.4-1.4A5.2 5.2 0 0 0 12 6.8zm0 2.2a3 3 0 1 1 0 6 3 3 0 0 1 0-6z" fill="#fff" />
    </svg>
  ),
  whatsapp: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <path fill="#25D366" d="M12 2a10 10 0 0 0-8.6 15.1L2 22l4.9-1.3A10 10 0 1 0 12 2z" />
      <path fill="#fff" d="M16.8 13.6c-.3-.1-1.6-.8-1.8-.9-.2-.1-.4-.1-.6.1-.2.3-.6.8-.8 1-.1.1-.3.2-.5.1-.7-.3-1.5-.7-2.3-1.6-.6-.7-1-1.5-1.1-1.7-.1-.2 0-.4.1-.5l.4-.5c.1-.2.2-.3.1-.5l-.8-1.9c-.2-.4-.4-.4-.6-.4h-.5c-.2 0-.5.1-.7.4-.3.3-.9.9-.9 2.2s.9 2.6 1.1 2.7c.1.2 1.9 3 4.7 4 2.2.8 2.7.7 3.2.6.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2-.1-.1-.3-.2-.5-.3z" />
    </svg>
  ),
  custom_mcp_server: (
    <svg viewBox="0 0 24 24" className="h-full w-full" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M9 2v6M15 2v6" />
      <path d="M6 8h12v3a6 6 0 0 1-12 0z" />
      <path d="M12 17v4" />
    </svg>
  ),
  filesystem: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <path d="M3 6.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="#E0A800" />
      <path d="M3 10h18" stroke="#fff" strokeWidth="1.4" opacity="0.5" />
    </svg>
  ),
  wikipedia: (
    <svg viewBox="0 0 24 24" className="h-full w-full" fill="currentColor" aria-hidden>
      <path d="M2 6h2.1l3 7.9L10.1 6h1.8l3 7.9L18 6h2.1l-4.1 12h-1.9l-3-7.8L8.1 18H6.2z" />
    </svg>
  ),
  wikidata: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <path d="M3 5h2v14H3zM7 5h2v14H7zM11 5h2v14h-2z" fill="#990000" />
      <path d="M15 5h2v14h-2z" fill="#339966" />
      <path d="M19 5h2v14h-2z" fill="#006699" />
    </svg>
  ),
  gleif: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <circle cx="12" cy="5" r="2.5" fill="#00A3E0" />
      <circle cx="6" cy="18" r="2.5" fill="#00A3E0" />
      <circle cx="18" cy="18" r="2.5" fill="#00A3E0" />
      <path d="M12 7.5v4M12 11.5l-6 4M12 11.5l6 4" stroke="#00A3E0" strokeWidth="1.6" fill="none" />
    </svg>
  ),
  job_search_mcp: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <rect x="3" y="7" width="18" height="13" rx="2" fill="#0F766E" />
      <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" stroke="#0F766E" strokeWidth="1.8" fill="none" />
      <path d="M3 12.5h18" stroke="#fff" strokeWidth="1.4" opacity="0.6" />
    </svg>
  ),
  news_mcp: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <rect x="3" y="4" width="18" height="16" rx="2" fill="#4F46E5" />
      <path d="M6 8h7M6 11h7M6 14h12M6 17h12" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" />
      <rect x="14.5" y="7" width="3.5" height="5" rx="0.6" fill="#fff" />
    </svg>
  ),
  tavily: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <circle cx="10.5" cy="10.5" r="7" fill="none" stroke="#0EA5A4" strokeWidth="2.2" />
      <path d="M16 16l5 5" stroke="#0EA5A4" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M10.5 6.5l1.1 2.9 2.9 1.1-2.9 1.1-1.1 2.9-1.1-2.9-2.9-1.1 2.9-1.1z" fill="#0EA5A4" />
    </svg>
  ),
  firecrawl: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <path d="M12 2.5c.6 3-2.2 4.3-2.2 7 0 1.1.6 2 1.4 2.4-.2-1.6.8-2.8 2-3.6.2 2.4 3.3 3.4 3.3 6.8A4.9 4.9 0 0 1 12 20a4.9 4.9 0 0 1-4.5-5c0-4.6 4.8-6.2 4.5-12.5z" fill="#FA5D19" />
    </svg>
  ),
  travelpayouts: (
    <svg viewBox="0 0 24 24" className="h-full w-full" aria-hidden>
      <path d="M21 16v-2l-8-5V4a1.6 1.6 0 0 0-3.2 0v5l-8 5v2l8-2.6v4.2l-2.2 1.6V20l4-1 4 1v-1.8l-2.2-1.6v-4.2z" fill="#2563EB" />
    </svg>
  ),
};

/** Name fragments → icon key, most specific first. */
const MATCH: [RegExp, string][] = [
  [/quickbooks/i, "quickbooks_pro"],
  [/sheets?/i, "google_sheets"],
  [/gmail|google mail/i, "gmail"],
  [/slack/i, "slack"],
  [/notion/i, "notion"],
  [/github/i, "github"],
  [/atlassian|confluence/i, "atlassian"],
  [/jira/i, "jira"],
  [/linear/i, "linear"],
  [/whats ?app/i, "whatsapp"],
  [/file ?system|files?\b/i, "filesystem"],
  [/wikidata/i, "wikidata"],
  [/wikipedia/i, "wikipedia"],
  [/gleif|\blei\b/i, "gleif"],
  [/job/i, "job_search_mcp"],
  [/news/i, "news_mcp"],
  [/tavily/i, "tavily"],
  [/firecrawl/i, "firecrawl"],
  [/travel|flight/i, "travelpayouts"],
  [/custom/i, "custom_mcp_server"],
];

export function connectorKey(name: string): string | null {
  return MATCH.find(([re]) => re.test(name))?.[1] ?? null;
}

export function ConnectorIcon({ name, size = "md", className }: { name: string; size?: "xs" | "sm" | "md"; className?: string }) {
  const key = connectorKey(name);
  const icon = (key && ICONS[key]) || <Puzzle className="h-full w-full text-zinc-400" />;
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-xl border border-zinc-200 bg-zinc-50 text-zinc-100",
        size === "xs" ? "h-5 w-5 rounded-md p-0.5" : size === "sm" ? "h-9 w-9 p-2" : "h-12 w-12 p-2.5",
        className,
      )}
    >
      {icon}
    </div>
  );
}

/** Small emerald check: the card and the panel header share it. */
export function VerifiedBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn("inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-[10px] font-bold text-white", className)}
      title="Connected"
      aria-label="Connected"
    >
      ✓
    </span>
  );
}
