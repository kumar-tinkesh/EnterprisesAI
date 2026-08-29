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
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AuditLogsPanel } from "@/components/audit-logs-panel";
import { SsoConfigPanel } from "@/components/sso-config-panel";
import { useAuthStore } from "@/stores/auth-store";
import { api, ApiError, type TenantMember } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/auth-fields";

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

  return (
    <ProtectedDashboard
      path="/tenant"
      title="Tenant Admin Dashboard"
      description="Manage your organization, members, and workspaces."
    >
      {/* Stat Cards */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs">
          <div className="flex items-center gap-2 text-zinc-500">
            <Building2 className="h-5 w-5 text-indigo-600" /> Workspaces
          </div>
          <p className="mt-2 text-3xl font-bold text-zinc-900">
            {statsLoading ? "…" : stats?.workspace_count ?? 0}
          </p>
        </div>
        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs">
          <div className="flex items-center gap-2 text-zinc-500">
            <Users className="h-5 w-5 text-violet-600" /> Members
          </div>
          <p className="mt-2 text-3xl font-bold text-zinc-900">
            {statsLoading ? "…" : stats?.member_count ?? 0}
          </p>
        </div>
      </div>

      {/* Members Section */}
      <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-900">Organization Members</h2>
            <p className="text-sm text-zinc-500">
              List of users belonging to your tenant organization.
            </p>
          </div>
          <Button onClick={() => setShowAddModal(true)} size="sm">
            <UserPlus className="h-4 w-4 mr-1" /> Add Member
          </Button>
        </div>

        {membersLoading ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-6 w-6 text-zinc-500" />
          </div>
        ) : members.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-400">
            No members found. Click "Add Member" to invite users.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm text-zinc-600">
              <thead className="bg-zinc-50 text-xs font-semibold uppercase text-zinc-500">
                <tr>
                  <th className="px-4 py-3">Member</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {members.map((m) => {
                  const isSelf = m.id === currentUser?.id;
                  return (
                    <tr key={m.id} className="hover:bg-zinc-50/50">
                      <td className="px-4 py-3">
                        <div className="font-medium text-zinc-900">{m.full_name || "—"}</div>
                        <div className="text-xs text-zinc-400">{m.email}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            m.is_active
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-rose-100 text-rose-700"
                          }`}
                        >
                          {m.is_active ? (
                            <>
                              <UserCheck className="h-3 w-3" /> Active
                            </>
                          ) : (
                            <>
                              <UserX className="h-3 w-3" /> Inactive
                            </>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setEditingMember(m)}
                            className="p-1 text-zinc-400 hover:text-zinc-700 cursor-pointer"
                            title="Edit member"
                          >
                            <Edit2 className="h-4 w-4" />
                          </button>
                          {!isSelf && (
                            <button
                              onClick={() => {
                                if (
                                  confirm(
                                    `Are you sure you want to remove ${m.email} from the organization?`
                                  )
                                ) {
                                  deleteMutation.mutate(m.id);
                                }
                              }}
                              className="p-1 text-zinc-400 hover:text-red-600 cursor-pointer"
                              title="Delete member"
                              disabled={deleteMutation.isPending}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Member Modal */}
      {showAddModal && (
        <AddMemberModal
          onClose={() => setShowAddModal(false)}
          onSubmit={(vals) => addMutation.mutate(vals)}
          isPending={addMutation.isPending}
          error={
            addMutation.isError
              ? addMutation.error instanceof ApiError
                ? addMutation.error.message
                : "Failed to add member"
              : null
          }
        />
      )}

      {/* Edit Member Modal */}
      {editingMember && (
        <EditMemberModal
          member={editingMember}
          onClose={() => setEditingMember(null)}
          onSubmit={(vals) =>
            editMutation.mutate({ id: editingMember.id, body: vals })
          }
          isPending={editMutation.isPending}
          error={
            editMutation.isError
              ? editMutation.error instanceof ApiError
                ? editMutation.error.message
                : "Failed to update member"
              : null
          }
        />
      )}

      <SsoConfigPanel />
      <AuditLogsPanel limit={25} />
    </ProtectedDashboard>
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
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
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
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
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