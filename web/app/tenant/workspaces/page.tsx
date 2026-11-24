"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, ChevronRight, Plus, Search, Users } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { WorkspacePanel } from "@/components/workspaces/workspace-panel";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";
import { useWorkspaces, workspacesApi } from "@/lib/workspaces";

const date = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/** The organization admin's workspaces: make one per team, decide who is in it. */
export default function TenantWorkspacesPage() {
  const token = useAuthStore((s) => s.accessToken) || "";
  const client = useQueryClient();
  const q = useWorkspaces(true);
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");

  const create = useMutation({
    mutationFn: () => workspacesApi.create(token, { name: name.trim(), description: desc.trim() }),
    onSuccess: (ws) => {
      void client.invalidateQueries({ queryKey: ["workspaces"] });
      setCreating(false);
      setName("");
      setDesc("");
      setOpenId(ws.id); // straight on to adding its people
    },
  });

  const all = q.data?.workspaces ?? [];
  const archivedCount = all.filter((w) => w.status === "archived").length;
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return all.filter(
      (w) =>
        (showArchived || w.status === "active") &&
        (!needle || w.name.toLowerCase().includes(needle) || w.description.toLowerCase().includes(needle)),
    );
  }, [all, search, showArchived]);
  const open = all.find((w) => w.id === openId) ?? null;

  return (
    <ProtectedDashboard
      path="/tenant"
      title="Workspaces"
      description="One per team. Each workspace's agents, workflows, chats and knowledge are seen only by its members."
      action={
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> New workspace
        </Button>
      }
    >
      <div className="mt-6 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-0 flex-1 sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input className="pl-9" placeholder="Find a workspace" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {archivedCount > 0 && (
            <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-600">
              <input type="checkbox" className="h-4 w-4 accent-indigo-600" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
              Show archived ({archivedCount})
            </label>
          )}
        </div>

        {q.isLoading ? (
          <div className="flex justify-center py-16"><Spinner className="h-5 w-5 text-zinc-400" /></div>
        ) : q.isError ? (
          <p className="text-sm text-red-600">Couldn&apos;t load workspaces.</p>
        ) : shown.length === 0 ? (
          <p className="rounded-lg border border-dashed border-zinc-200 p-8 text-center text-sm text-zinc-500">
            {search ? "No workspace matches that." : "No workspaces yet."}
          </p>
        ) : (
          <ul className="divide-y divide-zinc-100 overflow-hidden rounded-lg border border-zinc-200 bg-white">
            {shown.map((w) => (
              <li key={w.id}>
                <button
                  type="button"
                  onClick={() => setOpenId(w.id)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-zinc-50 cursor-pointer"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
                    <Building2 className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-zinc-900">{w.name}</span>
                      {w.status === "archived" && (
                        <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-400">Archived</span>
                      )}
                    </span>
                    <span className="block truncate text-xs text-zinc-500">{w.description || "No description"}</span>
                  </span>
                  <span className="hidden shrink-0 items-center gap-1.5 text-xs text-zinc-500 sm:flex">
                    <Users className="h-3.5 w-3.5" /> {w.member_count}
                  </span>
                  <span className="hidden w-28 shrink-0 text-right text-xs text-zinc-500 md:block">{date(w.created_at)}</span>
                  <ChevronRight className={cn("h-4 w-4 shrink-0 text-zinc-400")} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {creating && (
        <Dialog title="New workspace" onClose={() => setCreating(false)}>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create.mutate();
            }}
          >
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-zinc-700">Name</span>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sales, HR, Support" maxLength={120} autoFocus />
            </label>
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-zinc-700">What it&apos;s for <span className="text-zinc-400">(optional)</span></span>
              <Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="A line your team will recognise" maxLength={500} />
            </label>
            {create.isError && (
              <p role="alert" className="text-sm text-[var(--danger)]">
                {create.error instanceof Error ? create.error.message : "Couldn't create it."}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setCreating(false)}>Cancel</Button>
              <Button type="submit" disabled={!name.trim() || create.isPending}>
                {create.isPending && <Spinner className="h-4 w-4" />} Create
              </Button>
            </div>
          </form>
        </Dialog>
      )}

      {open && <WorkspacePanel workspace={open} token={token} onClose={() => setOpenId(null)} />}
    </ProtectedDashboard>
  );
}
