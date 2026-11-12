"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users,
  Building2,
  UserPlus,
  Trash2,
  Edit2,
  UserCheck,
  UserX,
  X,
  Eye,
  EyeOff,
  Search,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AuditLogsPanel } from "@/components/audit-logs-panel";
import { useAuthStore } from "@/stores/auth-store";
import { api, ApiError, type TenantMember } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/auth-fields";
import { cn } from "@/lib/utils";

export default function TenantDashboard() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const currentUser = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();

  // Modals state
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingMember, setEditingMember] = useState<TenantMember | null>(null);

  // Queries
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["tenant-stats", accessToken],
    queryFn: () => api.getTenantStats(accessToken),
    enabled: !!accessToken,
  });

  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ["tenant-members", accessToken],
    queryFn: () => api.getTenantMembers(accessToken),
    enabled: !!accessToken,
  });

  // Add Member mutation (creates tenant_user by default)
  const addMutation = useMutation({
    mutationFn: (values: { email: string; password: string; full_name: string }) =>
      api.createTenantMember(accessToken, { ...values, role: "tenant_user" }),
    onSuccess: () => {
      setShowAddModal(false);
      queryClient.invalidateQueries({ queryKey: ["tenant-members"] });
      queryClient.invalidateQueries({ queryKey: ["tenant-stats"] });
    },
  });

  // Edit Member mutation
  const editMutation = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: { full_name?: string; is_active?: boolean; password?: string };
    }) => api.updateTenantMember(accessToken, id, body),
    onSuccess: () => {
      setEditingMember(null);
      queryClient.invalidateQueries({ queryKey: ["tenant-members"] });
    },
  });

  // Delete Member mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteTenantMember(accessToken, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tenant-members"] });
      queryClient.invalidateQueries({ queryKey: ["tenant-stats"] });
    },
  });

  const [search, setSearch] = useState("");
  const [asking, setAsking] = useState<{ id: string; what: "remove" | "deactivate" } | null>(null);
  const q = search.trim().toLowerCase();
  const activeCount = members.filter((m) => m.is_active).length;
  const shown = members
    .filter((m) => !q || [m.full_name, m.email].some((x) => (x || "").toLowerCase().includes(q)))
    // You first, then admins, then by name.
    .sort((a, b) =>
      Number(b.id === currentUser?.id) - Number(a.id === currentUser?.id) ||
      Number(b.role === "tenant_admin") - Number(a.role === "tenant_admin") ||
      (a.full_name || a.email).localeCompare(b.full_name || b.email),
    );

  return (
    <ProtectedDashboard path="/tenant" title="Organization admin" description="Your organization's people and workspaces.">
      <div className="mt-6 grid grid-cols-3 gap-3">
        <Stat icon={<Users className="h-4 w-4" />} label="Members" value={statsLoading ? "…" : stats?.member_count ?? members.length} />
        <Stat icon={<UserCheck className="h-4 w-4" />} label="Can sign in" value={membersLoading ? "…" : activeCount} />
        <Stat icon={<Building2 className="h-4 w-4" />} label="Workspaces" value={statsLoading ? "…" : stats?.workspace_count ?? 0} />
      </div>

      <section className="mt-8 overflow-hidden rounded-xl border border-zinc-200">
        <div className="flex flex-col gap-3 border-b border-zinc-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-base font-semibold text-zinc-900">Members</h2>
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1 sm:w-56">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
              <Input aria-label="Search members" className="h-9 pl-8" placeholder="Search name or email" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <Button onClick={() => setShowAddModal(true)} size="sm" className="h-9 shrink-0">
              <UserPlus className="h-4 w-4" /> Add member
            </Button>
          </div>
        </div>
        <p className="border-b border-zinc-100 px-4 py-2 text-xs text-zinc-500">
          <b className="font-medium text-zinc-700">Admin</b>: adds and removes members and sees everyone&apos;s activity.{" "}
          <b className="font-medium text-zinc-700">Member</b>: builds and runs their own agents with their own apps.
        </p>
        {deleteMutation.isError && (
          <p className="border-b border-zinc-100 bg-red-50 px-4 py-2 text-xs text-red-700">
            {deleteMutation.error instanceof ApiError ? deleteMutation.error.message : "Couldn't remove that member."}
          </p>
        )}

        {membersLoading ? (
          <div className="flex justify-center py-8"><Spinner className="h-6 w-6 text-zinc-500" /></div>
        ) : members.length === 0 ? (
          <div className="px-6 py-10 text-center">
            <p className="text-sm text-zinc-700">No members yet.</p>
            <Button className="mt-3" size="sm" onClick={() => setShowAddModal(true)}><UserPlus className="h-4 w-4" /> Add the first one</Button>
          </div>
        ) : shown.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-zinc-500">No member matches that.</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {shown.map((m) => {
              const isSelf = m.id === currentUser?.id;
              const ask = asking?.id === m.id ? asking.what : null;
              const busy = deleteMutation.isPending || editMutation.isPending;
              return (
                <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-sm font-medium text-zinc-700">
                    {(m.full_name || m.email).charAt(0).toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate text-sm font-medium text-zinc-900">{m.full_name || m.email}</span>
                      {isSelf && <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600">You</span>}
                      <span className={cn("rounded-full px-2 py-0.5 text-xs", m.role === "tenant_admin" ? "bg-indigo-50 text-indigo-700" : "bg-zinc-100 text-zinc-600")}>
                        {m.role === "tenant_admin" ? "Admin" : "Member"}
                      </span>
                      {!m.is_active && <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs text-rose-700">Can&apos;t sign in</span>}
                    </span>
                    <span className="block truncate text-xs text-zinc-500">
                      {m.email} · joined {new Date(m.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
                    </span>
                  </span>
                  {ask ? (
                    <span className="flex shrink-0 items-center gap-2 text-xs">
                      <span className="text-zinc-600">{ask === "remove" ? `Remove ${m.full_name || m.email}?` : "Stop them signing in?"}</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          if (ask === "remove") deleteMutation.mutate(m.id, { onSuccess: () => setAsking(null) });
                          else editMutation.mutate({ id: m.id, body: { is_active: false } }, { onSuccess: () => setAsking(null) });
                        }}
                        className="rounded-md bg-red-600 px-2 py-1 font-medium text-white hover:bg-red-700 disabled:opacity-50 cursor-pointer"
                      >
                        {busy ? "…" : "Yes"}
                      </button>
                      <button type="button" onClick={() => setAsking(null)} className="rounded-md px-2 py-1 text-zinc-500 hover:bg-zinc-100 cursor-pointer">No</button>
                    </span>
                  ) : (
                    <span className="flex shrink-0 items-center gap-1">
                      <Button type="button" size="sm" variant="ghost" className="h-8 text-zinc-600" onClick={() => setEditingMember(m)}>
                        <Edit2 className="h-4 w-4" /> <span className="hidden sm:inline">Edit</span>
                      </Button>
                      {!isSelf && (m.is_active ? (
                        <Button type="button" size="sm" variant="ghost" className="h-8 text-zinc-600" onClick={() => setAsking({ id: m.id, what: "deactivate" })}>
                          <UserX className="h-4 w-4" /> <span className="hidden sm:inline">Block</span>
                        </Button>
                      ) : (
                        <Button type="button" size="sm" variant="outline" className="h-8" disabled={busy} onClick={() => editMutation.mutate({ id: m.id, body: { is_active: true } })}>
                          <UserCheck className="h-4 w-4" /> Let in
                        </Button>
                      ))}
                      {!isSelf && (
                        <Button type="button" size="sm" variant="ghost" className="h-8 text-zinc-500 hover:text-red-600" aria-label={`Remove ${m.email}`} onClick={() => setAsking({ id: m.id, what: "remove" })}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {showAddModal && (
        <AddMemberModal
          onClose={() => setShowAddModal(false)}
          onSubmit={(vals) => addMutation.mutate(vals)}
          isPending={addMutation.isPending}
          error={addMutation.isError ? (addMutation.error instanceof ApiError ? addMutation.error.message : "Failed to add member") : null}
        />
      )}

      {editingMember && (
        <EditMemberModal
          member={editingMember}
          onClose={() => setEditingMember(null)}
          onSubmit={(vals) => editMutation.mutate({ id: editingMember.id, body: vals })}
          isPending={editMutation.isPending}
          error={editMutation.isError ? (editMutation.error instanceof ApiError ? editMutation.error.message : "Failed to update member") : null}
        />
      )}

      <AuditLogsPanel limit={25} />
    </ProtectedDashboard>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">{icon}{label}</div>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums text-zinc-900">{value}</p>
    </div>
  );
}

function AddMemberModal({
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  onClose: () => void;
  onSubmit: (vals: { email: string; password: string; full_name: string }) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!fullName || !email || !password) return;
    onSubmit({ full_name: fullName, email, password });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-[var(--surface-raised)] p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Add Tenant Member</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Full Name">
            <Input
              placeholder="John Doe"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
          </Field>
          <Field label="Email Address">
            <Input
              type="email"
              placeholder="john@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>
          <Field label="Password">
            <div className="relative">
              <Input
                type={showPassword ? "text" : "password"}
                placeholder="At least 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 cursor-pointer"
                title={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </Field>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : <UserPlus className="h-4 w-4 mr-1" />} Add Member
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditMemberModal({
  member,
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  member: TenantMember;
  onClose: () => void;
  onSubmit: (vals: { full_name?: string; is_active?: boolean; password?: string }) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [fullName, setFullName] = useState(member.full_name);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isActive, setIsActive] = useState(member.is_active);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload: { full_name?: string; is_active?: boolean; password?: string } = {
      full_name: fullName,
      is_active: isActive,
    };
    if (password.trim().length > 0) {
      payload.password = password;
    }
    onSubmit(payload);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-[var(--surface-raised)] p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Edit Member</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Full Name">
            <Input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
          </Field>

          <Field label="Email Address">
            <Input
              type="email"
              value={member.email}
              disabled
              className="bg-zinc-100 text-zinc-500 cursor-not-allowed"
            />
          </Field>

          <Field label="New Password (optional)">
            <div className="relative">
              <Input
                type={showPassword ? "text" : "password"}
                placeholder="Leave blank to keep unchanged"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 cursor-pointer"
                title={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </Field>

          <Field label="Account Status">
            <label className="flex items-center gap-2 text-sm text-zinc-700 cursor-pointer pt-1">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="h-4 w-4 rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
              />
              Active Account
            </label>
          </Field>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : "Save Changes"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}