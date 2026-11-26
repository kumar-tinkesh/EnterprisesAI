"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bot,
  Brain,
  Building2,
  ChevronRight,
  ChevronsUpDown,
  Command,
  Globe,
  LayoutDashboard,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  Zap,
} from "lucide-react";

import { Avatar } from "@/components/builder/chat/chat-message";
import { CommandPalette } from "@/components/command-palette";
import { Menu as ActionMenu } from "@/components/ui/menu";
import { builderApi } from "@/lib/builder/api";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";
import { useSwitchWorkspace, useWorkspaces } from "@/lib/workspaces";

type NavItem = {
  href: string;
  label: string;
  Icon: typeof LayoutDashboard;
  badge?: string | number;
};

const USER_NAV: NavItem[] = [
  { href: "/user", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/user/agents", label: "Agents & Workflows", Icon: Bot },
  { href: "/user/executions", label: "Executions & Logs", Icon: Zap },
  { href: "/user/analytics", label: "Analytics & Costs", Icon: BarChart3 },
  { href: "/user/connectors", label: "Connectors", Icon: Plug },
  { href: "/user/knowledge", label: "Knowledge Base", Icon: Brain },
  { href: "/user/published", label: "Published", Icon: Globe },
  { href: "/user/workspaces", label: "Workspaces", Icon: Building2 },
  { href: "/user/settings", label: "Settings", Icon: Settings },
];

/** The admins' menus: the same frame, their own pages. */
export const SHELLS: Record<
  "user" | "vendor" | "tenant",
  { home: string; nav: NavItem[]; caption?: string }
> = {
  user: { home: "/user", nav: USER_NAV },
  vendor: {
    home: "/vendor",
    caption: "Platform admin",
    nav: [
      { href: "/vendor", label: "Overview", Icon: LayoutDashboard },
      { href: "/vendor/accounts", label: "Accounts", Icon: Building2 },
      { href: "/vendor/tools", label: "Apps", Icon: Plug },
      { href: "/vendor/activity", label: "Activity", Icon: Activity },
    ],
  },
  tenant: {
    home: "/tenant",
    caption: "Organization admin",
    nav: [
      { href: "/tenant", label: "Members", Icon: Users },
      { href: "/tenant/workspaces", label: "Workspaces", Icon: Building2 },
      { href: "/tenant/settings", label: "Security & SSO", Icon: ShieldCheck },
      { href: "/tenant/activity", label: "Activity", Icon: Activity },
    ],
  },
};

const COLLAPSED_KEY = "user-shell.collapsed";

/**
 * The signed-in user's app frame: a sidebar (collapsible to icons on wide
 * screens, a drawer on phones) beside the page. Full-bleed pages (canvas,
 * editors, chat) fill the space next to it.
 */
export function UserShell({
  fullBleed,
  shell = "user",
  children,
}: {
  fullBleed?: boolean;
  shell?: keyof typeof SHELLS;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const frame = SHELLS[shell];
  const [cmdOpen, setCmdOpen] = useState(false);

  // Global Cmd+K / Ctrl+K shortcut
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Read up front (the shell only renders in the browser, after sign-in is checked) so it doesn't jump width on load.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [drawer, setDrawer] = useState(false);
  useEffect(() => setDrawer(false), [pathname]);

  const toggle = () => {
    setCollapsed((c) => {
      try {
        window.localStorage.setItem(COLLAPSED_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  };

  // Human readable breadcrumb segment
  const currentNav = frame.nav.find((n) =>
    n.href === frame.home ? pathname === frame.home : pathname.startsWith(n.href),
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-[var(--bg)] md:flex-row">
      {/* Command Palette */}
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />

      {/* Phone: a top bar opens the sidebar as a drawer. */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/10 bg-[var(--surface)] px-3 md:hidden">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setDrawer(true)}
            aria-label="Open menu"
            className="rounded-md p-1.5 text-zinc-400 hover:bg-white/5 cursor-pointer"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Brand home={frame.home} />
        </div>
        <button
          type="button"
          onClick={() => setCmdOpen(true)}
          className="rounded-md p-1.5 text-zinc-400 hover:bg-white/5"
          aria-label="Search"
        >
          <Search className="h-4 w-4" />
        </button>
      </div>

      {drawer && (
        <div
          className="fixed inset-0 z-50 md:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Menu"
        >
          <button
            type="button"
            aria-label="Close menu"
            className="animate-fade-in absolute inset-0 bg-black/60 backdrop-blur-xs"
            onClick={() => setDrawer(false)}
          />
          <div className="animate-slide-in-left relative flex h-full w-72 max-w-[85vw] flex-col border-r border-white/10 bg-[var(--surface)] shadow-2xl">
            <button
              type="button"
              onClick={() => setDrawer(false)}
              aria-label="Close menu"
              className="absolute right-2 top-3 rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
            <SidebarBody
              pathname={pathname}
              collapsed={false}
              frame={frame}
              onOpenCmd={() => setCmdOpen(true)}
            />
          </div>
        </div>
      )}

      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-white/10 bg-[var(--surface)] transition-[width] duration-200 md:flex",
          collapsed
            ? "w-16 min-w-16 max-w-16"
            : "w-64 min-w-64 max-w-64 lg:w-72 lg:min-w-72 lg:max-w-72",
        )}
      >
        <SidebarBody
          pathname={pathname}
          collapsed={collapsed}
          onToggle={toggle}
          frame={frame}
          onOpenCmd={() => setCmdOpen(true)}
        />
      </aside>

      <main className="min-h-0 min-w-0 flex-1 flex flex-col overflow-y-auto">
        {/* Top utility bar on wider screens when not fullBleed */}
        {!fullBleed && (
          <div className="hidden h-12 shrink-0 items-center justify-between border-b border-white/5 bg-[var(--surface)] px-6 md:flex">
            <div className="flex items-center gap-2 text-xs text-zinc-400">
              <span className="font-medium text-zinc-300">
                {shell === "user" ? "Workspace" : shell === "tenant" ? "Organization" : "Platform"}
              </span>
              <ChevronRight className="h-3 w-3 text-zinc-600" />
              <span className="font-semibold text-[var(--text)]">
                {currentNav?.label || "Overview"}
              </span>
            </div>

            <button
              type="button"
              onClick={() => setCmdOpen(true)}
              className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-white/20 hover:bg-white/[0.08] hover:text-white cursor-pointer"
            >
              <Search className="h-3.5 w-3.5" />
              <span>Search or jump to...</span>
              <kbd className="ml-2 flex items-center gap-0.5 rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-mono text-zinc-300">
                <Command className="h-2.5 w-2.5" /> K
              </kbd>
            </button>
          </div>
        )}

        {/* Content */}
        <div key={fullBleed ? "bleed" : pathname} className={cn("flex-1 min-h-0", !fullBleed && "animate-fade-up")}>
          {fullBleed ? <div className="h-full [&>div]:h-full">{children}</div> : children}
        </div>
      </main>
    </div>
  );
}

function Brand({ collapsed, home = "/user" }: { collapsed?: boolean; home?: string }) {
  return (
    <Link href={home} className="group flex min-w-0 items-center gap-2.5">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] text-white shadow-[0_0_16px_-2px_rgba(99,102,241,0.55)] ring-1 ring-white/20 transition-transform duration-200 group-hover:scale-105">
        <Sparkles className="h-4 w-4" />
      </span>
      {!collapsed && (
        <div className="min-w-0">
          <span className="block truncate text-sm font-semibold tracking-tight text-zinc-900 leading-none">
            EnterpriseAI
          </span>
          <span className="block text-[10px] font-medium text-zinc-400 uppercase tracking-widest mt-0.5">
            Cloud Suite
          </span>
        </div>
      )}
    </Link>
  );
}

function SidebarBody({
  pathname,
  collapsed,
  onToggle,
  frame,
  onOpenCmd,
}: {
  pathname: string;
  collapsed: boolean;
  onToggle?: () => void;
  frame: (typeof SHELLS)[keyof typeof SHELLS];
  onOpenCmd?: () => void;
}) {
  const router = useRouter();
  const token = useAuthStore((s) => s.accessToken) || "";
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const team = user?.role === "tenant_user";
  // Workspaces are a team thing: a personal account has exactly one, so it
  // gets no switcher and no Workspaces page.
  const workspacesQ = useWorkspaces();
  const currentWs = workspacesQ.data?.workspaces.find((w) => w.is_current);
  const nav = frame.nav.filter((n) => n.href !== "/user/workspaces" || team);

  // Check pending approvals to show notification badge on Executions
  const approvalsQ = useQuery({
    queryKey: ["builder-approvals"],
    queryFn: () => builderApi.listApprovals(token),
    enabled: !!token,
    refetchInterval: 20000,
  });
  const pendingCount = (approvalsQ.data ?? []).length;

  return (
    <>
      <div
        className={cn(
          "flex h-14 shrink-0 items-center gap-2 border-b border-white/10",
          collapsed ? "justify-center px-2" : "pl-4 pr-2",
        )}
      >
        {!(collapsed && onToggle) && <Brand home={frame.home} />}
        {onToggle && (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "rounded-md p-1.5 text-zinc-400 hover:bg-white/5 hover:text-zinc-200 cursor-pointer",
              !collapsed && "ml-auto",
            )}
          >
            {collapsed ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <PanelLeftClose className="h-4 w-4" />
            )}
          </button>
        )}
      </div>

      {team && frame.home === "/user" && workspacesQ.data?.can_switch && (
        <WorkspaceSwitcher collapsed={collapsed} />
      )}

      {/* Quick Search Shortcut Bar */}
      {!collapsed && onOpenCmd && (
        <div className="p-2 pb-1">
          <button
            type="button"
            onClick={onOpenCmd}
            className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-xs text-zinc-400 transition-colors hover:border-white/20 hover:bg-white/[0.08] hover:text-white cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <Search className="h-3.5 w-3.5 text-zinc-400" />
              <span>Quick jump...</span>
            </div>
            <kbd className="rounded border border-white/10 bg-white/10 px-1.5 py-0.5 text-[10px] font-mono text-zinc-300">
              ⌘K
            </kbd>
          </button>
        </div>
      )}

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Main">
        {nav.map(({ href, label, Icon }) => {
          const active = href === frame.home ? pathname === frame.home : pathname.startsWith(href);
          const isExecutions = href === "/user/executions";
          const showBadge = isExecutions && pendingCount > 0;

          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150",
                collapsed && "justify-center px-0",
                active
                  ? "bg-[var(--surface-strong)] text-[var(--text)] shadow-xs"
                  : "text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-100",
              )}
            >
              {active && !collapsed && (
                <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-r bg-[var(--accent-hover)]" aria-hidden />
              )}
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0 transition-transform duration-150 group-hover:scale-105",
                  active ? "text-[var(--link)]" : "text-zinc-400 group-hover:text-zinc-200",
                )}
              />
              {!collapsed && <span className="truncate flex-1">{label}</span>}
              {showBadge && (
                <span
                  className={cn(
                    "relative flex items-center justify-center rounded-full bg-amber-500 text-white font-semibold tabular-nums",
                    collapsed
                      ? "absolute top-1 right-1 h-2 w-2 p-0"
                      : "h-5 min-w-5 px-1.5 text-[11px]",
                  )}
                  title={`${pendingCount} pending decision(s)`}
                >
                  <span className="absolute inset-0 animate-ping rounded-full bg-amber-400 opacity-50" aria-hidden />
                  <span className="relative">{!collapsed && pendingCount}</span>
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="shrink-0 border-t border-white/10 p-2 space-y-1">
        {user && (
          <Link
            href="/user/settings"
            className={cn(
              "flex items-center gap-2 rounded-lg p-2 transition-colors hover:bg-white/[0.04]",
              collapsed && "justify-center",
            )}
            title={collapsed ? `${user.full_name || user.email}` : undefined}
          >
            <Avatar name={user.full_name || user.email} size={32} />
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-100">
                  {user.full_name || user.email}
                </p>
                <p className="truncate text-xs text-zinc-500">
                  {frame.caption ?? (team ? currentWs?.name ?? "Team workspace" : "Personal workspace")}
                </p>
              </div>
            )}
          </Link>
        )}

        <button
          type="button"
          onClick={() => {
            logout();
            router.replace("/auth");
          }}
          title={user ? `Sign out (${user.email})` : "Sign out"}
          className={cn(
            "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200 cursor-pointer",
            collapsed && "justify-center px-0",
          )}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && "Sign out"}
        </button>
      </div>
    </>
  );
}

/** Which workspace you're in, and the others you can switch to (team accounts
 * in more than one workspace only). */
function WorkspaceSwitcher({ collapsed }: { collapsed: boolean }) {
  const router = useRouter();
  const { data } = useWorkspaces();
  const { switchTo, busy } = useSwitchWorkspace();
  const active = (data?.workspaces ?? []).filter((w) => w.status === "active");
  const current = active.find((w) => w.is_current);
  if (!data || active.length < 2) return null;

  const items = [
    ...active.map((w, i) => ({
      label: w.name,
      checked: w.is_current,
      header: i === 0 ? "Switch workspace" : undefined,
      onClick: () => {
        if (!w.is_current) void switchTo(w.id);
      },
    })),
    { label: "All workspaces…", divided: true, onClick: () => router.push("/user/workspaces") },
  ];

  return (
    <div className={cn("px-2 pt-2", collapsed && "flex justify-center")}>
      <ActionMenu
        label="Switch workspace"
        items={items}
        width={232}
        triggerClassName={cn(
          "flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] text-left transition-colors hover:border-white/20 hover:bg-white/[0.06] cursor-pointer",
          collapsed ? "h-9 w-9 justify-center" : "w-full px-2.5 py-2",
        )}
        trigger={
          <>
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--accent-wash)] text-xs font-semibold text-[var(--link)]">
              {(current?.name ?? "W").slice(0, 1).toUpperCase()}
            </span>
            {!collapsed && (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block text-xs text-zinc-500">{busy ? "Switching…" : "Workspace"}</span>
                  <span className="block truncate text-sm font-medium text-zinc-900">{current?.name ?? "Choose one"}</span>
                </span>
                <ChevronsUpDown className="h-4 w-4 shrink-0 text-zinc-400" />
              </>
            )}
          </>
        }
      />
    </div>
  );
}
