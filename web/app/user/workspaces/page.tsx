"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Building2, Check, Users } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";
import { useSwitchWorkspace, useWorkspaces } from "@/lib/workspaces";

/** A team member's workspaces: which one they're in, and switching. Your
 * organization admin decides who is in which. A personal account has exactly
 * one workspace, so it never comes here. */
export default function WorkspacesPage() {
  const router = useRouter();
  const role = useAuthStore((s) => s.user?.role);
  const q = useWorkspaces();
  const { switchTo, busy, error } = useSwitchWorkspace();

  useEffect(() => {
    if (role === "solo_user") router.replace("/user");
  }, [role, router]);

  const workspaces = q.data?.workspaces ?? [];

  return (
    <ProtectedDashboard
      path="/user"
      title="Workspaces"
      description="Each workspace has its own agents, workflows, chats and knowledge. Your organization admin decides who is in which."
    >
      <div className="mt-6 space-y-4">
        {error && (
          <p role="alert" className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-wash)] px-3 py-2 text-sm text-[var(--danger)]">
            {error}
          </p>
        )}

        {q.isLoading ? (
          <div className="flex justify-center py-16"><Spinner className="h-5 w-5 text-zinc-400" /></div>
        ) : q.isError ? (
          <p className="text-sm text-red-600">Couldn&apos;t load your workspaces.</p>
        ) : (
          <>
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {workspaces.map((w) => (
                <li
                  key={w.id}
                  className={cn(
                    "flex flex-col justify-between rounded-lg border p-4",
                    w.is_current ? "border-[var(--accent-border)] bg-[var(--accent-wash)]" : "border-zinc-200 bg-white",
                  )}
                >
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
                      <Building2 className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <h2 className="truncate text-sm font-medium text-zinc-900">{w.name}</h2>
                      <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500">{w.description || "No description"}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                      <Users className="h-3.5 w-3.5" /> {w.member_count} {w.member_count === 1 ? "member" : "members"}
                      {w.my_role === "admin" && <span className="ml-1 rounded-full bg-zinc-100 px-2 py-0.5 text-zinc-600">Admin</span>}
                    </span>
                    {w.is_current ? (
                      <span className="flex items-center gap-1 text-xs font-medium text-[var(--success)]">
                        <Check className="h-3.5 w-3.5" /> You&apos;re here
                      </span>
                    ) : (
                      <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void switchTo(w.id)}>
                        {busy === w.id && <Spinner className="h-3.5 w-3.5" />} Switch
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            {workspaces.length === 1 && (
              <p className="text-sm text-zinc-500">
                You&apos;re in one workspace. When your admin adds you to another, you can switch here or from the sidebar.
              </p>
            )}
          </>
        )}
      </div>
    </ProtectedDashboard>
  );
}
