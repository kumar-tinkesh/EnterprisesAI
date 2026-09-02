"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  Users,
  UserCheck,
  FolderKanban,
  Plus,
  Trash2,
  PauseCircle,
  PlayCircle,
  X,
  Eye,
  EyeOff,
  User,
  ShieldCheck,
  Server,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AuditLogsPanel } from "@/components/audit-logs-panel";
import { useAuthStore } from "@/stores/auth-store";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/auth-fields";

export default function VendorDashboard() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const [showAddModal, setShowAddModal] = useState(false);

  // Queries
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["vendor-stats", accessToken],
    queryFn: () => api.getVendorStats(accessToken),
    enabled: !!accessToken,
  });

  const { data: tenants = [], isLoading: tenantsLoading } = useQuery({
    queryKey: ["vendor-tenants", accessToken],
    queryFn: () => api.getVendorTenants(accessToken),
    enabled: !!accessToken,
  });

  // Mutations
  const addMutation = useMutation({
    mutationFn: (vals: {
      name: string;
      slug?: string;
      admin_email: string;
      admin_full_name: string;
      admin_password: string;
    }) => api.createVendorTenant(accessToken, vals),
    onSuccess: () => {
      setShowAddModal(false);
      queryClient.invalidateQueries({ queryKey: ["vendor-tenants"] });
      queryClient.invalidateQueries({ queryKey: ["vendor-stats"] });
    },
  });

  const toggleStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.updateVendorTenant(accessToken, id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vendor-tenants"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteVendorTenant(accessToken, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vendor-tenants"] });
      queryClient.invalidateQueries({ queryKey: ["vendor-stats"] });
    },
  });

  const [activeTab, setActiveTab] = useState<"all" | "team" | "solo">("all");

  const teamTenantsCount = tenants.filter((t) => !t.is_personal).length;
  const soloTenantsCount = tenants.filter((t) => t.is_personal).length;

  const filteredTenants = tenants.filter((t) => {
    if (activeTab === "team") return !t.is_personal;
    if (activeTab === "solo") return t.is_personal;
    return true;
  });

  return (
    <ProtectedDashboard
      path="/vendor"
      title="Vendor Admin Dashboard"
      description="Platform-level administration & tenant management for EnterpriseAI."
    >
      {/* MCP Servers shortcut */}
      <div className="mt-6 flex justify-end">
        <a
          href="/vendor/tools"
          className="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700"
        >
          <Server className="h-4 w-4" /> Manage MCP Servers
        </a>
      </div>

      {/* 4 Platform Metric Cards */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<Building2 className="h-5 w-5 text-indigo-600" />}
          label="Team Organizations"
          value={statsLoading ? "…" : stats?.total_tenants ?? 0}
        />
        <StatCard
          icon={<UserCheck className="h-5 w-5 text-purple-600" />}
          label="Individual Users"
          value={statsLoading ? "…" : stats?.individual_users ?? 0}
        />
        <StatCard
          icon={<Users className="h-5 w-5 text-sky-600" />}
          label="Total Platform Users"
          value={statsLoading ? "…" : stats?.total_users ?? 0}
        />
        <StatCard
          icon={<FolderKanban className="h-5 w-5 text-amber-600" />}
          label="Total Workspaces"
          value={statsLoading ? "…" : stats?.total_workspaces ?? 0}
        />
      </div>

      {/* Tenant Management Table */}
      <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-zinc-100 pb-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-900">Managed Tenants & Accounts</h2>
            <p className="text-sm text-zinc-500">
              Overview of all organization tenants and individual user accounts.
            </p>
          </div>
          <Button onClick={() => setShowAddModal(true)} size="sm">
            <Plus className="h-4 w-4 mr-1" /> Create Tenant
          </Button>
        </div>

        {/* Tab Switcher */}
        <div className="mt-4 flex border-b border-zinc-200 gap-6 text-sm font-medium">
          <button
            onClick={() => setActiveTab("all")}
            className={`pb-3 relative cursor-pointer ${
              activeTab === "all"
                ? "text-zinc-900 border-b-2 border-indigo-600 font-semibold"
                : "text-zinc-500 hover:text-zinc-700"
            }`}
          >
            All Accounts ({tenants.length})
          </button>
          <button
            onClick={() => setActiveTab("team")}
            className={`pb-3 relative cursor-pointer flex items-center gap-1.5 ${
              activeTab === "team"
                ? "text-indigo-600 border-b-2 border-indigo-600 font-semibold"
                : "text-zinc-500 hover:text-zinc-700"
            }`}
          >
            <Building2 className="h-4 w-4" /> Team Organizations ({teamTenantsCount})
          </button>
          <button
            onClick={() => setActiveTab("solo")}
            className={`pb-3 relative cursor-pointer flex items-center gap-1.5 ${
              activeTab === "solo"
                ? "text-purple-600 border-b-2 border-purple-600 font-semibold"
                : "text-zinc-500 hover:text-zinc-700"
            }`}
          >
            <User className="h-4 w-4" /> Solo Accounts ({soloTenantsCount})
          </button>
        </div>

        {tenantsLoading ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-6 w-6 text-zinc-500" />
          </div>
        ) : filteredTenants.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-400">
            No accounts found in this view.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm text-zinc-600">
              <thead className="bg-zinc-50 text-xs font-semibold uppercase text-zinc-500">
                <tr>
                  <th className="px-4 py-3">Tenant / Account</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Owner / Admin</th>
                  <th className="px-4 py-3 text-center">Users</th>
                  <th className="px-4 py-3 text-center">Workspaces</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {filteredTenants.map((t) => (
                  <tr key={t.id} className="hover:bg-zinc-50/50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-900">{t.name}</div>
                      <div className="text-xs text-zinc-400">slug: {t.slug}</div>
                    </td>
                    <td className="px-4 py-3">
                      {t.is_personal ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-700">
                          <User className="h-3 w-3" /> Solo Account
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                          <Building2 className="h-3 w-3" /> Team Org
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-zinc-800 font-medium text-xs">
                        {t.admin_name || "—"}
                      </div>
                      <div className="text-xs text-zinc-400">{t.admin_email || "—"}</div>
                    </td>
                    <td className="px-4 py-3 text-center font-semibold text-zinc-800">
                      {t.user_count}
                    </td>
                    <td className="px-4 py-3 text-center font-semibold text-zinc-800">
                      {t.workspace_count}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          t.status === "active"
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-rose-100 text-rose-700"
                        }`}
                      >
                        {t.status === "active" ? "Active" : "Suspended"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() =>
                            toggleStatusMutation.mutate({
                              id: t.id,
                              status: t.status === "active" ? "suspended" : "active",
                            })
                          }
                          className="p-1 text-zinc-400 hover:text-zinc-700 cursor-pointer"
                          title={t.status === "active" ? "Suspend tenant" : "Activate tenant"}
                        >
                          {t.status === "active" ? (
                            <PauseCircle className="h-4 w-4 text-amber-600" />
                          ) : (
                            <PlayCircle className="h-4 w-4 text-emerald-600" />
                          )}
                        </button>
                        <button
                          onClick={() => {
                            if (
                              confirm(
                                `Are you sure you want to delete tenant "${t.name}"? This will permanently delete all associated workspaces and users.`
                              )
                            ) {
                              deleteMutation.mutate(t.id);
                            }
                          }}
                          className="p-1 text-zinc-400 hover:text-red-600 cursor-pointer"
                          title="Delete tenant"
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Tenant Modal */}
      {showAddModal && (
        <CreateTenantModal
          onClose={() => setShowAddModal(false)}
          onSubmit={(vals) => addMutation.mutate(vals)}
          isPending={addMutation.isPending}
          error={
            addMutation.isError
              ? addMutation.error instanceof ApiError
                ? addMutation.error.message
                : "Failed to create tenant"
              : null
          }
        />
      )}

      <AuditLogsPanel limit={25} />
    </ProtectedDashboard>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs">
      <div className="flex items-center gap-2 text-zinc-500">{icon}{label}</div>
      <p className="mt-2 text-3xl font-bold text-zinc-900">{value}</p>
    </div>
  );
}

function CreateTenantModal({
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  onClose: () => void;
  onSubmit: (vals: {
    name: string;
    admin_email: string;
    admin_full_name: string;
    admin_password: string;
  }) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [name, setName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !adminName || !adminEmail || !adminPassword) return;
    onSubmit({
      name,
      admin_full_name: adminName,
      admin_email: adminEmail,
      admin_password: adminPassword,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Create New Tenant</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Organization Name">
            <Input
              placeholder="Acme Corporation"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </Field>

          <div className="border-t border-zinc-100 pt-3">
            <h4 className="text-xs font-semibold uppercase text-zinc-400 mb-3">
              Initial Tenant Admin Account
            </h4>

            <div className="space-y-4">
              <Field label="Admin Full Name">
                <Input
                  placeholder="Jane Smith"
                  value={adminName}
                  onChange={(e) => setAdminName(e.target.value)}
                  required
                />
              </Field>

              <Field label="Admin Email">
                <Input
                  type="email"
                  placeholder="admin@acme.com"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  required
                />
              </Field>

              <Field label="Admin Password">
                <div className="relative">
                  <Input
                    type={showPassword ? "text" : "password"}
                    placeholder="At least 8 characters"
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    required
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 cursor-pointer"
                    title={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </Field>
            </div>
          </div>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : <Plus className="h-4 w-4 mr-1" />} Create Tenant
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}