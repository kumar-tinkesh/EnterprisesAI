/** Connectors as people know them: which app a server is, its proper name, and what it does. */

/** Name fragments → icon key, most specific first. */
const MATCH: [RegExp, string][] = [
  [/quickbooks/i, "quickbooks_pro"],
  [/calend[ae]r|calander/i, "calendar"],
  [/linke?d ?in|linkdin/i, "linkedin"],
  [/jobspy|startup job/i, "jobs"],
  [/web ?search/i, "web_search"],
  [/sheets?/i, "google_sheets"],
  [/gmail|google mail/i, "gmail"],
  [/slack/i, "slack"],
  [/notion/i, "notion"],
  [/github/i, "github"],
  [/atlass?ian|confluence/i, "atlassian"],
  [/jira/i, "jira"],
  [/linear/i, "linear"],
  [/whats ?app/i, "whatsapp"],
  [/file ?system|files?\b/i, "filesystem"],
  [/wikidata/i, "wikidata"],
  [/wikipedia/i, "wikipedia"],
  [/gleif|glief|clief|\blei\b/i, "gleif"],
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

/** What people call each app, and what it lets an agent do, by icon key. */
const APPS: Record<string, { title: string; blurb: string }> = {
  gmail: { title: "Gmail", blurb: "Read, search and draft emails" },
  google_sheets: { title: "Google Sheets", blurb: "Read and update spreadsheets" },
  calendar: { title: "Google Calendar", blurb: "See and create events" },
  slack: { title: "Slack", blurb: "Read channels and post messages" },
  notion: { title: "Notion", blurb: "Read and write pages and databases" },
  whatsapp: { title: "WhatsApp", blurb: "Send messages (always asks first)" },
  atlassian: { title: "Atlassian", blurb: "Jira issues and Confluence pages" },
  jira: { title: "Jira", blurb: "Read and update issues" },
  linear: { title: "Linear", blurb: "Read and update issues" },
  github: { title: "GitHub", blurb: "Repositories, issues and pull requests" },
  linkedin: { title: "LinkedIn", blurb: "Search people, companies and jobs" },
  filesystem: { title: "Files", blurb: "Read and write files in a folder" },
  wikipedia: { title: "Wikipedia", blurb: "Look up articles" },
  wikidata: { title: "Wikidata", blurb: "Facts about companies, people and places" },
  gleif: { title: "GLEIF", blurb: "Companies' official legal records" },
  news_mcp: { title: "News", blurb: "Recent news articles" },
  tavily: { title: "Tavily", blurb: "Search the web" },
  web_search: { title: "Web search", blurb: "Search the web" },
  firecrawl: { title: "Firecrawl", blurb: "Read whole web pages" },
  travelpayouts: { title: "Travel", blurb: "Flights and hotels" },
  quickbooks_pro: { title: "QuickBooks", blurb: "Invoices, bills and accounts" },
};

/** Specific apps that share an icon key ("jobs", "job_search_mcp"). */
const NAMED: [RegExp, { title: string; blurb: string }][] = [
  [/jobspy/i, { title: "JobSpy", blurb: "Indeed, Naukri, Glassdoor and Google Jobs" }],
  [/startup job/i, { title: "Startup Jobs", blurb: "Jobs at startups" }],
  [/job ?search/i, { title: "Job search", blurb: "Search job boards" }],
];

/**
 * A connector's name and one line on what it does, the way a person would say
 * them: admins name servers freely ("gmail", "linkdin server"), so known apps get
 * their proper name; anything else is tidied ("file system server" -> "File system").
 * The description is used when it says more than the name.
 */
export function appLabel(name: string, description?: string | null): { title: string; blurb: string } {
  const known = NAMED.find(([re]) => re.test(name))?.[1] ?? APPS[connectorKey(name) ?? ""];
  if (known) return known;
  const bare = tidyName(name);
  const desc = (description ?? "").trim();
  // "gmail server", "filesystem": a description that only repeats the name says nothing.
  const norm = (x: string) => x.toLowerCase().replace(/mcp|server/g, "").replace(/[^a-z0-9]/g, "");
  return { title: bare, blurb: desc && norm(desc) !== norm(name) ? desc : "" };
}


/** A server's own name without "server"/"mcp", first letter up ("file system server" -> "File system"). */
export function tidyName(name: string): string {
  const bare = name.replace(/[\s_-]*\b(mcp|server)\b/gi, "").trim() || name;
  return bare.charAt(0).toUpperCase() + bare.slice(1);
}
