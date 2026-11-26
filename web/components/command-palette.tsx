"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BarChart3,
  Bot,
  Brain,
  Building2,
  Calendar,
  Compass,
  FileText,
  Globe,
  HelpCircle,
  LayoutDashboard,
  LogOut,
  Plug,
  Plus,
  Search,
  Settings,
  Sparkles,
  Users,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

interface CommandItem {
  id: string;
  title: string;
  subtitle?: string;
  icon: typeof Bot;
  category: "Navigation" | "Quick Actions" | "Tools & Hub";
  action: () => void;
  shortcut?: string;
  roles?: string[];
}

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const navigate = (path: string) => {
    router.push(path);
    onClose();
  };

  const commands: CommandItem[] = [
    // Quick Actions
    {
      id: "action-new-agent",
      title: "Create New Agent",
      subtitle: "Build with conversational AI compiler",
      icon: Plus,
      category: "Quick Actions",
      action: () => navigate("/user/agents"),
      shortcut: "N",
    },
    {
      id: "action-upload-doc",
      title: "Upload Knowledge Document",
      subtitle: "Add PDF, CSV, DOCX to vector knowledge base",
      icon: Brain,
      category: "Quick Actions",
      action: () => navigate("/user/knowledge"),
    },

    // Navigation
    {
      id: "nav-dashboard",
      title: "Dashboard",
      subtitle: "Workspace overview and pending approvals",
      icon: LayoutDashboard,
      category: "Navigation",
      action: () => navigate("/user"),
      shortcut: "G D",
    },
    {
      id: "nav-agents",
      title: "Agents & Workflows",
      subtitle: "Visual graph canvas & AI compiler",
      icon: Bot,
      category: "Navigation",
      action: () => navigate("/user/agents"),
      shortcut: "G A",
    },
    {
      id: "nav-executions",
      title: "Executions & Logs",
      subtitle: "Live traces, debugging & run history",
      icon: Zap,
      category: "Navigation",
      action: () => navigate("/user/executions"),
      shortcut: "G E",
    },
    {
      id: "nav-analytics",
      title: "Analytics & Token Costs",
      subtitle: "Token usage breakdown & latency metrics",
      icon: BarChart3,
      category: "Navigation",
      action: () => navigate("/user/analytics"),
    },
    {
      id: "nav-connectors",
      title: "Connectors & MCP Tools",
      subtitle: "Connect Slack, Gmail, GitHub & Custom MCPs",
      icon: Plug,
      category: "Navigation",
      action: () => navigate("/user/connectors"),
    },
    {
      id: "nav-knowledge",
      title: "Knowledge Base",
      subtitle: "Enterprise documents, RAG & semantic search",
      icon: Brain,
      category: "Navigation",
      action: () => navigate("/user/knowledge"),
    },
    {
      id: "nav-published",
      title: "Published & Share Links",
      subtitle: "Public agent URLs, API keys & QR codes",
      icon: Globe,
      category: "Navigation",
      action: () => navigate("/user/published"),
    },
    // A personal account has one workspace: nothing to switch or manage.
    ...(user?.role === "tenant_user"
      ? [
          {
            id: "nav-workspaces",
            title: "Workspaces",
            subtitle: "Switch between your team's workspaces",
            icon: Building2,
            category: "Navigation" as const,
            action: () => navigate("/user/workspaces"),
          },
        ]
      : []),
    {
      id: "nav-settings",
      title: "Settings & Profile",
      subtitle: "Account preferences, themes & API keys",
      icon: Settings,
      category: "Navigation",
      action: () => navigate("/user/settings"),
      shortcut: "G S",
    },

    // Admin pages (if tenant admin or vendor admin)
    ...(user?.role === "tenant_admin"
      ? [
          {
            id: "nav-tenant-members",
            title: "Tenant Members",
            subtitle: "Manage organization team members",
            icon: Users,
            category: "Tools & Hub" as const,
            action: () => navigate("/tenant"),
          },
          {
            id: "nav-tenant-workspaces",
            title: "Tenant Workspaces",
            subtitle: "Organization-wide workspace controls",
            icon: Building2,
            category: "Tools & Hub" as const,
            action: () => navigate("/tenant/workspaces"),
          },
          {
            id: "nav-tenant-settings",
            title: "Organization Security & SSO",
            subtitle: "SSO settings & domain policies",
            icon: Settings,
            category: "Tools & Hub" as const,
            action: () => navigate("/tenant/settings"),
          },
        ]
      : []),

    {
      id: "action-sign-out",
      title: "Sign Out",
      subtitle: `Signed in as ${user?.email || "user"}`,
      icon: LogOut,
      category: "Tools & Hub",
      action: () => {
        logout();
        navigate("/auth");
      },
    },
  ];

  const filtered = commands.filter((c) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return (
      c.title.toLowerCase().includes(q) ||
      (c.subtitle && c.subtitle.toLowerCase().includes(q)) ||
      c.category.toLowerCase().includes(q)
    );
  });

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % (filtered.length || 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev === 0 ? Math.max(0, filtered.length - 1) : prev - 1,
        );
      } else if (e.key === "Enter" && filtered[selectedIndex]) {
        e.preventDefault();
        filtered[selectedIndex].action();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, filtered, selectedIndex]);

  if (!open) return null;

  // Group by category
  const categories = ["Quick Actions", "Navigation", "Tools & Hub"] as const;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-16 sm:pt-24"
      role="dialog"
      aria-modal="true"
      aria-label="Command Palette"
    >
      <button
        type="button"
        aria-label="Close command palette"
        className="animate-fade-in fixed inset-0 bg-black/65 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      <div className="animate-scale-in relative flex max-h-[80dvh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-[var(--surface-raised)] shadow-2xl ring-1 ring-white/10">
        {/* Search header */}
        <div className="flex items-center gap-3 border-b border-white/10 px-4 py-3">
          <Search className="h-5 w-5 shrink-0 text-zinc-400" />
          <input
            autoFocus
            type="text"
            className="flex-1 bg-transparent text-sm text-[var(--text)] placeholder-zinc-500 outline-none"
            placeholder="Type a command, page, or action (e.g. 'templates', 'new agent')..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <kbd className="hidden rounded bg-white/5 px-2 py-0.5 text-xs font-medium text-zinc-400 sm:inline-block">
            ESC
          </kbd>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Results list */}
        <div className="flex-1 overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <div className="py-12 text-center">
              <Compass className="mx-auto h-8 w-8 text-zinc-500 opacity-60" />
              <p className="mt-2 text-sm font-medium text-zinc-300">
                No matching commands found
              </p>
              <p className="text-xs text-zinc-500">
                Try searching for &quot;agent&quot;, &quot;executions&quot;, or &quot;templates&quot;
              </p>
            </div>
          ) : (
            categories.map((cat) => {
              const groupItems = filtered.filter((i) => i.category === cat);
              if (groupItems.length === 0) return null;

              return (
                <div key={cat} className="mb-2">
                  <div className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                    {cat}
                  </div>
                  <div className="space-y-0.5">
                    {groupItems.map((item) => {
                      const itemIndex = filtered.indexOf(item);
                      const isSelected = itemIndex === selectedIndex;
                      const Icon = item.icon;

                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={item.action}
                          onMouseEnter={() => setSelectedIndex(itemIndex)}
                          className={cn(
                            "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors cursor-pointer",
                            isSelected
                              ? "bg-[var(--accent-wash-strong)] text-white ring-1 ring-[var(--accent-border)]"
                              : "text-zinc-300 hover:bg-white/[0.04]",
                          )}
                        >
                          <span
                            className={cn(
                              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border",
                              isSelected
                                ? "border-[var(--accent-border)] bg-[var(--accent)] text-white"
                                : "border-white/10 bg-white/[0.05] text-zinc-400",
                            )}
                          >
                            <Icon className="h-3.5 w-3.5" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="font-medium truncate">{item.title}</p>
                            {item.subtitle && (
                              <p className="text-xs text-zinc-400 truncate">
                                {item.subtitle}
                              </p>
                            )}
                          </div>
                          {item.shortcut && (
                            <span className="shrink-0 rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">
                              {item.shortcut}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer hints */}
        <div className="flex items-center justify-between border-t border-white/10 bg-white/[0.02] px-4 py-2 text-[11px] text-zinc-500">
          <div className="flex items-center gap-2">
            <span>↑↓ to navigate</span>
            <span>·</span>
            <span>↵ to select</span>
            <span>·</span>
            <span>esc to close</span>
          </div>
          <span className="font-medium text-zinc-400">EnterpriseAI v2.0</span>
        </div>
      </div>
    </div>
  );
}
