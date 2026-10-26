"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Bot, Brain, Globe, LayoutDashboard, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Plug, Sparkles, X, Zap } from "lucide-react";

import { Avatar } from "@/components/builder/chat/chat-message";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/user", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/user/agents", label: "AI Compiler", Icon: Bot },
  { href: "/user/executions", label: "Executions", Icon: Zap },
  { href: "/user/published", label: "Published", Icon: Globe },
  { href: "/user/connectors", label: "Connectors", Icon: Plug },
  { href: "/user/knowledge", label: "Knowledge Base", Icon: Brain },
];

const COLLAPSED_KEY = "user-shell.collapsed";

/**
 * The signed-in user's app frame: a sidebar (collapsible to icons on wide
 * screens, a drawer on phones) beside the page. Full-bleed pages (canvas,
 * editors, chat) fill the space next to it.
 */
export function UserShell({ fullBleed, children }: { fullBleed?: boolean; children: React.ReactNode }) {
  const pathname = usePathname();
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

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-[var(--bg)] md:flex-row">
      {/* Phone: a top bar opens the sidebar as a drawer. */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-zinc-200 bg-white px-3 md:hidden">
        <button type="button" onClick={() => setDrawer(true)} aria-label="Open menu" className="rounded-md p-1.5 text-zinc-600 hover:bg-zinc-100 cursor-pointer">
          <Menu className="h-5 w-5" />
        </button>
        <Brand />
      </div>
      {drawer && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-zinc-900/40" onClick={() => setDrawer(false)} />
          <div className="relative flex h-full w-72 max-w-[85vw] flex-col bg-white shadow-xl">
            <button type="button" onClick={() => setDrawer(false)} aria-label="Close menu" className="absolute right-2 top-3 rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 cursor-pointer">
              <X className="h-4 w-4" />
            </button>
            <SidebarBody pathname={pathname} collapsed={false} />
          </div>
        </div>
      )}

      <aside className={cn("hidden shrink-0 flex-col border-r border-zinc-200 bg-white transition-[width] duration-200 md:flex", collapsed ? "w-16" : "w-60")}>
        <SidebarBody pathname={pathname} collapsed={collapsed} onToggle={toggle} />
      </aside>

      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        {/* Full-bleed pages size themselves to the screen; here they fill the space beside the sidebar. */}
        {fullBleed ? <div className="h-full [&>div]:h-full">{children}</div> : children}
      </main>
    </div>
  );
}

function Brand({ collapsed }: { collapsed?: boolean }) {
  return (
    <Link href="/user" className="flex min-w-0 items-center gap-2">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--accent)] text-white">
        <Sparkles className="h-4 w-4" />
      </span>
      {!collapsed && <span className="truncate text-sm font-semibold tracking-tight text-zinc-900">EnterpriseAI</span>}
    </Link>
  );
}

function SidebarBody({ pathname, collapsed, onToggle }: { pathname: string; collapsed: boolean; onToggle?: () => void }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const team = user?.role === "tenant_user";

  return (
    <>
      <div className={cn("flex h-14 shrink-0 items-center gap-2 border-b border-zinc-100", collapsed ? "justify-center px-2" : "pl-4 pr-2")}>
        {/* Collapsed, the header is just the way back open. */}
        {!(collapsed && onToggle) && <Brand />}
        {onToggle && (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn("rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 cursor-pointer", !collapsed && "ml-auto")}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        )}
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Main">
        {NAV.map(({ href, label, Icon }) => {
          const active = href === "/user" ? pathname === "/user" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                collapsed && "justify-center px-0",
                active ? "bg-[var(--surface-strong)] text-[var(--text)]" : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900",
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", active ? "text-[var(--link)]" : "text-zinc-400")} />
              {!collapsed && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className="shrink-0 border-t border-zinc-100 p-2">
        {user && (
          <div className={cn("flex items-center gap-2 rounded-lg p-2", collapsed && "justify-center")} title={collapsed ? `${user.full_name || user.email}` : undefined}>
            <Avatar name={user.full_name || user.email} size={32} />
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-900">{user.full_name || user.email}</p>
                <p className="truncate text-xs text-zinc-500">{team ? "Team workspace" : "Personal workspace"}</p>
              </div>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={() => {
            logout();
            router.replace("/auth");
          }}
          title={user ? `Sign out (${user.email})` : "Sign out"}
          className={cn("flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900 cursor-pointer", collapsed && "justify-center px-0")}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && "Sign out"}
        </button>
      </div>
    </>
  );
}
