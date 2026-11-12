"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  Users,
  UserCheck,
  Plus,
  Search,
  Trash2,
  PauseCircle,
  PlayCircle,
  X,
  Eye,
  EyeOff,
  User,
  Server,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AuditLogsPanel } from "@/components/audit-logs-panel";
import { useAuthStore } from "@/stores/auth-store";
import { api, ApiError, vendorApi } from "@/lib/api";
import { appLabel } from "@/lib/connectors";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/auth-fields";

export default function VendorDashboard() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const [showAddModal, setShowAddModal] = useState(false);
  const [activeTab, setActiveTab] = useState<"all" | "team" | "solo" | "suspended">("all");
  const [search, setSearch] = useState("");
  const [asking, setAsking] = useState<{ id: string; what: "delete" | "suspend" } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["vendor-stats", accessToken],
    queryFn: () => api.getVendorStats(accessToken),
    enabled: !!accessToken,
  });
  const { data: tenants = [], isLoading: tenantsLoading, isError: tenantsFailed } = useQuery({
    queryKey: ["vendor-tenants", accessToken],
    queryFn: () => api.getVendorTenants(accessToken),
    enabled: !!accessToken,
  });
  const { data: servers = [] } = useQuery({
    queryKey: ["vendor-mcp-servers", accessToken],
    queryFn: () => vendorApi.listMCPServers(accessToken),
    enabled: !!accessToken,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["vendor-tenants"] });
    queryClient.invalidateQueries({ queryKey: ["vendor-stats"] });
  };
  const fail = (err: unknown) => setError(err instanceof ApiError ? err.message : "Something went wrong.");

  const addMutation = useMutation({
    mutationFn: (vals: { name: string; slug?: string; admin_email: string; admin_full_name: string; admin_password: string }) =>
      api.createVendorTenant(accessToken, vals),
    onSuccess: () => {
      setShowAddModal(false);
      refresh();
    },
  });
  const toggleStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.updateVendorTenant(accessToken, id, { status }),
    onSuccess: () => {
      setAsking(null);
      refresh();
    },
    onError: fail,
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteVendorTenant(accessToken, id),
    onSuccess: () => {
      setAsking(null);
      refresh();
    },
    onError: fail,
  });

  // What needs the admin: apps nobody can use yet, accounts that are switched off.
  const appsToFix = servers.filter((s) => s.status !== "VERIFIED" || !(s.bound_tools?.length ?? 0));
  const appsReady = servers.length - appsToFix.length;
  const suspended = tenants.filter((t) => t.status !== "active");
  const teamCount = tenants.filter((t) => !t.is_personal).length;
  const soloCount = tenants.filter((t) => t.is_personal).length;
  const names = Object.fromEntries(servers.map((s) => [s.id, appLabel(s.name, s.description).title]));

  const q = search.trim().toLowerCase();
  const shown = tenants
    .filter((t) =>
      activeTab === "team" ? !t.is_personal : activeTab === "solo" ? t.is_personal : activeTab === "suspended" ? t.status !== "active" : true,
    )
    .filter((t) => !q || [t.name, t.slug, t.admin_name, t.admin_email].some((x) => (x || "").toLowerCase().includes(q)))
    .sort((a, b) => Number(a.is_personal) - Number(b.is_personal) || a.name.localeCompare(b.name));
  const TABS = [
    ["all", "All", tenants.length],
    ["team", "Organizations", teamCount],
    ["solo", "Solo", soloCount],
    ["suspended", "Suspended", suspended.length],
  ] as const;

  return (
    <ProtectedDashboard path="/vendor" title="Platform admin" description="Organizations, people and the apps they can connect.">
      <div className="mt-6 flex flex-wrap justify-end gap-2">
        <a href="/vendor/tools" className="inline-flex h-9 items-center gap-1.5 rounded-md border border-zinc-200 px-3 text-sm font-medium text-zinc-900 hover:bg-zinc-50">
          <Server className="h-4 w-4" /> Apps
        </a>
        <Button size="sm" className="h-9" onClick={() => setShowAddModal(true)}>
          <Plus className="h-4 w-4" /> New organization
        </Button>
      </div>

      {/* What needs the admin now */}
      {(appsToFix.length > 0 || suspended.length > 0) && (
        <section className="mt-4 overflow-hidden rounded-xl border border-zinc-200">
          <h2 className="border-b border-zinc-100 px-4 py-3 text-base font-semibold text-zinc-900">Needs your attention</h2>
          <ul className="divide-y divide-zinc-100">
            {appsToFix.length > 0 && (
              <li>
                <a href="/vendor/tools" className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-zinc-900">
                      {appsToFix.length} app{appsToFix.length === 1 ? "" : "s"} can&apos;t be used yet
                    </span>
                    <span className="block truncate text-xs text-zinc-500">
                      {appsToFix.slice(0, 4).map((s) => appLabel(s.name, s.description).title).join(", ")}: test them so people can connect.
                    </span>
                  </span>
                  <span className="shrink-0 text-sm font-medium text-zinc-700">Open</span>
                </a>
              </li>
            )}
            {suspended.length > 0 && (
              <li>
                <button type="button" onClick={() => setActiveTab("suspended")} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-zinc-50 cursor-pointer">
                  <PauseCircle className="h-4 w-4 shrink-0 text-zinc-500" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-zinc-900">
                      {suspended.length} suspended account{suspended.length === 1 ? "" : "s"}
                    </span>
                    <span className="block truncate text-xs text-zinc-500">Their people can&apos;t sign in until you turn them back on.</span>
                  </span>
                  <span className="shrink-0 text-sm font-medium text-zinc-700">Show</span>
                </button>
              </li>
            )}
          </ul>
        </section>
      )}

      {/* The numbers that matter */}
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icon={<Users className="h-4 w-4" />} label="People" value={statsLoading ? "…" : stats?.total_users ?? 0} note="every account, solo and in organizations" />
        <StatCard icon={<Building2 className="h-4 w-4" />} label="Organizations" value={tenantsLoading ? "…" : teamCount} note={`${stats?.total_workspaces ?? 0} workspaces in all`} />
        <StatCard icon={<UserCheck className="h-4 w-4" />} label="Solo accounts" value={tenantsLoading ? "…" : soloCount} note="people who signed up on their own" />
        <StatCard
          icon={<Server className="h-4 w-4" />}
          label="Apps ready"
          value={servers.length ? `${appsReady} / ${servers.length}` : "…"}
          note={appsToFix.length ? `${appsToFix.length} need a test` : "all can be connected"}
          href="/vendor/tools"
        />
      </div>

      {/* Accounts */}
      <section className="mt-8 overflow-hidden rounded-xl border border-zinc-200">
        <div className="flex flex-col gap-3 border-b border-zinc-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-base font-semibold text-zinc-900">Accounts</h2>
          <div className="relative sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input aria-label="Search accounts" className="h-9 pl-8" placeholder="Search name or email" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 border-b border-zinc-100 px-4 py-2.5" role="group" aria-label="Filter accounts">
          {TABS.map(([id, text, n]) => (
            <button
              key={id}
              type="button"
              aria-pressed={activeTab === id}
              onClick={() => setActiveTab(id)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium cursor-pointer",
                activeTab === id ? "border-[var(--accent)] bg-[var(--accent)] text-white" : "border-zinc-200 text-zinc-600 hover:bg-zinc-50",
              )}
            >
              {text} <span className="tabular-nums opacity-75">{n}</span>
            </button>
          ))}
        </div>
        {error && <p className="border-b border-zinc-100 bg-red-50 px-4 py-2 text-xs text-red-700">{error}</p>}

        {tenantsLoading ? (
          <div className="flex justify-center py-8"><Spinner className="h-6 w-6 text-zinc-500" /></div>
        ) : tenantsFailed ? (
          <p className="px-4 py-8 text-center text-sm text-zinc-600">Couldn&apos;t load the accounts. Reload the page to try again.</p>
        ) : shown.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-zinc-500">{q ? "No account matches that." : "No accounts here."}</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {shown.map((t) => {
              const active = t.status === "active";
              const ask = asking?.id === t.id ? asking.what : null;
              return (
                <li key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                  <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", t.is_personal ? "bg-purple-50 text-purple-700" : "bg-indigo-50 text-indigo-700")}>
                    {t.is_personal ? <User className="h-4 w-4" /> : <Building2 className="h-4 w-4" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-zinc-900">{t.name}</span>
                      {!active && <span className="shrink-0 rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700">Suspended</span>}
                    </span>
                    <span className="block truncate text-xs text-zinc-500">
                      {t.is_personal ? "Solo" : "Organization"} · {t.admin_name || t.admin_email || "no admin"}
                      {t.admin_name && t.admin_email ? ` (${t.admin_email})` : ""}
                    </span>
                  </span>
                  <span className="hidden shrink-0 text-right text-xs tabular-nums text-zinc-500 sm:block">
                    {t.user_count} {t.user_count === 1 ? "person" : "people"}
                    <span className="block">{t.workspace_count} workspace{t.workspace_count === 1 ? "" : "s"}</span>
                  </span>
                  {ask ? (
                    <span className="flex shrink-0 items-center gap-2 text-xs">
                      <span className="text-zinc-600">
                        {ask === "delete" ? `Delete ${t.name}, its workspaces and people?` : `Suspend ${t.name}? Its people can't sign in.`}
                      </span>
                      <button
                        type="button"
                        disabled={deleteMutation.isPending || toggleStatusMutation.isPending}
                        onClick={() => (ask === "delete" ? deleteMutation.mutate(t.id) : toggleStatusMutation.mutate({ id: t.id, status: "suspended" }))}
                        className="rounded-md bg-red-600 px-2 py-1 font-medium text-white hover:bg-red-700 disabled:opacity-50 cursor-pointer"
                      >
                        {deleteMutation.isPending || toggleStatusMutation.isPending ? "…" : "Yes"}
                      </button>
                      <button type="button" onClick={() => setAsking(null)} className="rounded-md px-2 py-1 text-zinc-500 hover:bg-zinc-100 cursor-pointer">No</button>
                    </span>
                  ) : (
                    <span className="flex shrink-0 items-center gap-1">
                      {active ? (
                        <Button type="button" size="sm" variant="ghost" className="h-8 text-zinc-600" onClick={() => { setError(null); setAsking({ id: t.id, what: "suspend" }); }}>
                          <PauseCircle className="h-4 w-4" /> <span className="hidden sm:inline">Suspend</span>
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-8"
                          disabled={toggleStatusMutation.isPending}
                          onClick={() => toggleStatusMutation.mutate({ id: t.id, status: "active" })}
                        >
                          <PlayCircle className="h-4 w-4" /> Turn on
                        </Button>
                      )}
                      <Button type="button" size="sm" variant="ghost" className="h-8 text-zinc-500 hover:text-red-600" aria-label={`Delete ${t.name}`} onClick={() => { setError(null); setAsking({ id: t.id, what: "delete" }); }}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {showAddModal && (
        <CreateTenantModal
          onClose={() => setShowAddModal(false)}
          onSubmit={(vals) => addMutation.mutate(vals)}
          isPending={addMutation.isPending}
          error={addMutation.isError ? (addMutation.error instanceof ApiError ? addMutation.error.message : "Failed to create the organization") : null}
        />
      )}

      <AuditLogsPanel limit={25} names={names} />
    </ProtectedDashboard>
  );
}

function StatCard({ icon, label, value, note, href }: { icon: React.ReactNode; label: string; value: React.ReactNode; note?: string; href?: string }) {
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">{icon}{label}</div>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums text-zinc-900">{value}</p>
      {note && <p className="mt-0.5 text-xs text-zinc-500">{note}</p>}
    </>
  );
  return href ? (
    <a href={href} className="rounded-xl border border-zinc-200 p-4 hover:bg-zinc-50">{body}</a>
  ) : (
    <div className="rounded-xl border border-zinc-200 p-4">{body}</div>
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
      <div className="w-full max-w-md rounded-xl bg-[var(--surface-raised)] p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">New organization</h3>
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
              Its first admin
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
              {isPending ? <Spinner /> : <Plus className="h-4 w-4 mr-1" />} Create organization
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}