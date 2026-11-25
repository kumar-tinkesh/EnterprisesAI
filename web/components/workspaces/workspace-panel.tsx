"use client";

/** One workspace, opened from the admin's Workspaces page: its name and
 * description, who is in it (add, make admin, remove), and archive/restore. */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Building2, UserPlus, X } from "lucide-react";

import { Avatar } from "@/components/builder/chat/chat-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { workspacesApi, type Workspace } from "@/lib/workspaces";

function message(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong.";
}

export function WorkspacePanel({ workspace, token, onClose }: { workspace: Workspace; token: string; onClose: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description);
  const [adding, setAdding] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(workspace.name);
    setDescription(workspace.description);
  }, [workspace.id, workspace.name, workspace.description]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const membersQ = useQuery({
    queryKey: ["workspace-members", workspace.id],
    queryFn: () => workspacesApi.members(token, workspace.id),
    enabled: !!token,
  });
  // Everyone in the organization who could be added (the tenant's people).
  const peopleQ = useQuery({ queryKey: ["tenant-members"], queryFn: () => api.getTenantMembers(token), enabled: !!token });

  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["workspaces"] });
    void client.invalidateQueries({ queryKey: ["workspace-members", workspace.id] });
  };
  const run = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onMutate: () => setError(null),
    onSuccess: refresh,
    onError: (e) => setError(message(e)),
  });

  const members = membersQ.data ?? [];
  const inIt = new Set(members.map((m) => m.user_id));
  const candidates = (peopleQ.data ?? []).filter((p) => p.is_active && !inIt.has(p.id));
  const dirty = name.trim() !== workspace.name || description.trim() !== workspace.description;
  const archived = workspace.status === "archived";

  return (
    <div className="animate-fade-in fixed inset-0 z-40 flex justify-end bg-black/50 backdrop-blur-xs" onClick={onClose}>
      <aside
        className="animate-slide-in-right flex h-full w-full flex-col border-l border-white/10 bg-[var(--surface-raised)] shadow-2xl sm:w-[460px]"
        onClick={(e) => e.stopPropagation()}
        aria-label={`Workspace ${workspace.name}`}
      >
        <div className="flex items-start gap-3 border-b border-zinc-200 p-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
            <Building2 className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold text-zinc-900">{workspace.name}</h2>
            <p className="text-xs text-zinc-500">
              {workspace.member_count} {workspace.member_count === 1 ? "member" : "members"}
              {archived && <span className="ml-1.5 rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-400">Archived</span>}
            </p>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-zinc-400 hover:text-zinc-700 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">
          {error && (
            <p role="alert" className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-wash)] px-3 py-2 text-sm text-[var(--danger)]">
              {error}
            </p>
          )}

          <section className="space-y-3">
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-zinc-700">Name</span>
              <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
            </label>
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-zinc-700">What it&apos;s for</span>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} placeholder="e.g. Sales team's agents and workflows" />
            </label>
            {dirty && (
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => { setName(workspace.name); setDescription(workspace.description); }}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  disabled={!name.trim() || run.isPending}
                  onClick={() => run.mutate(() => workspacesApi.update(token, workspace.id, { name: name.trim(), description: description.trim() }))}
                >
                  Save
                </Button>
              </div>
            )}
          </section>

          <section>
            <h3 className="mb-2 text-sm font-medium text-zinc-900">Members</h3>
            <p className="mb-3 text-xs text-zinc-500">
              Only members see this workspace&apos;s agents, workflows, chats and knowledge. You (the organization admin) can
              always manage it.
            </p>

            <div className="mb-3 flex gap-2">
              <select
                aria-label="Person to add"
                value={adding}
                onChange={(e) => setAdding(e.target.value)}
                className="h-9 min-w-0 flex-1 rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 text-sm text-[var(--text)]"
              >
                <option value="">{candidates.length ? "Add a person…" : "Everyone is already in it"}</option>
                {candidates.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.full_name || p.email} · {p.email}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                className="h-9"
                disabled={!adding || run.isPending}
                onClick={() => run.mutate(async () => { await workspacesApi.addMember(token, workspace.id, adding); setAdding(""); })}
              >
                <UserPlus className="h-4 w-4" /> Add
              </Button>
            </div>

            {membersQ.isLoading ? (
              <div className="flex justify-center py-6"><Spinner className="h-5 w-5 text-zinc-400" /></div>
            ) : members.length === 0 ? (
              <p className="text-sm text-zinc-500">Nobody yet.</p>
            ) : (
              <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
                {members.map((m) => (
                  <li key={m.user_id} className="flex items-center gap-2.5 px-3 py-2.5">
                    <Avatar name={m.full_name || m.email} size={28} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-zinc-900">{m.full_name || m.email}</span>
                      <span className="block truncate text-xs text-zinc-500">{m.email}</span>
                    </span>
                    <span
                      className={cn(
                        "shrink-0 rounded-full px-2 py-0.5 text-xs",
                        m.role === "admin" ? "bg-indigo-50 text-indigo-700" : "bg-zinc-100 text-zinc-600",
                      )}
                    >
                      {m.role === "admin" ? "Admin" : "Member"}
                    </span>
                    <Menu
                      label={`Actions for ${m.full_name || m.email}`}
                      items={[
                        m.role === "admin"
                          ? { label: "Make member", onClick: () => run.mutate(() => workspacesApi.setRole(token, workspace.id, m.user_id, "member")) }
                          : { label: "Make admin", onClick: () => run.mutate(() => workspacesApi.setRole(token, workspace.id, m.user_id, "admin")) },
                        { label: "Remove from workspace", danger: true, divided: true, onClick: () => run.mutate(() => workspacesApi.removeMember(token, workspace.id, m.user_id)) },
                      ]}
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-zinc-200 p-3">
            <h3 className="text-sm font-medium text-zinc-900">{archived ? "Restore" : "Archive"}</h3>
            <p className="mt-1 text-xs text-zinc-500">
              {archived
                ? "Members can switch into it again; everything in it is still there."
                : "Nobody can switch into it while archived. Nothing is deleted — restore it any time."}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              disabled={run.isPending}
              onClick={() => run.mutate(() => workspacesApi.update(token, workspace.id, { status: archived ? "active" : "archived" }))}
            >
              {archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
              {archived ? "Restore workspace" : "Archive workspace"}
            </Button>
          </section>
        </div>
      </aside>
    </div>
  );
}
