"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Wrench,
  Plus,
  Trash2,
  Sparkles,
  Share2,
  X,
  Globe,
  Lock,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import { api, ApiError, type VendorTenant } from "@/lib/api";
import {
  vendorApi,
  type VendorTool,
  type CreateVendorToolBody,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/auth-fields";

export default function VendorToolsPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const [showAddModal, setShowAddModal] = useState(false);
  const [showGrantModal, setShowGrantModal] = useState(false);
  const [grantTool, setGrantTool] = useState<VendorTool | null>(null);

  // Queries
  const { data: tools = [], isLoading } = useQuery({
    queryKey: ["vendor-tools", accessToken],
    queryFn: () => vendorApi.listTools(accessToken),
    enabled: !!accessToken,
  });

  const { data: tenants = [] }: { data: VendorTenant[] | undefined } = useQuery({
    queryKey: ["vendor-tenants", accessToken],
    queryFn: () => api.getVendorTenants(accessToken),
    enabled: !!accessToken,
  });

  // Mutations
  const createMutation = useMutation({
    mutationFn: (vals: CreateVendorToolBody) => vendorApi.createTool(accessToken, vals),
    onSuccess: () => {
      setShowAddModal(false);
      queryClient.invalidateQueries({ queryKey: ["vendor-tools"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => vendorApi.deleteTool(accessToken, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vendor-tools"] }),
  });

  const embedMutation = useMutation({
    mutationFn: (id: string) => vendorApi.embedTool(accessToken, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vendor-tools"] }),
  });

  const grantMutation = useMutation({
    mutationFn: (vals: { tenant_id: string; resource_id: string }) =>
      vendorApi.grantResource(accessToken, {
        tenant_id: vals.tenant_id,
        resource_type: "vendor_tool",
        resource_id: vals.resource_id,
      }),
    onSuccess: () => setShowGrantModal(false),
  });

  return (
    <ProtectedDashboard
      path="/vendor"
      title="Vendor Tools"
      description="Register REST/OpenAPI tools, embed them for semantic matching, and grant access to tenants."
    >
      <div className="mt-6 flex items-center justify-between">
        <a href="/vendor" className="text-sm text-zinc-500 hover:text-zinc-800 cursor-pointer">
          ← Back to dashboard
        </a>
        <Button onClick={() => setShowAddModal(true)} size="sm">
          <Plus className="h-4 w-4 mr-1" /> Register Tool
        </Button>
      </div>

      <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-xs">
        <div className="flex items-center gap-2 border-b border-zinc-100 pb-4">
          <Wrench className="h-5 w-5 text-indigo-600" />
          <div>
            <h2 className="text-lg font-semibold text-zinc-900">Registered Vendor Tools</h2>
            <p className="text-sm text-zinc-500">
              Tools are embedded on create (best-effort) for the AI Compiler&apos;s semantic matcher.
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-6 w-6 text-zinc-500" />
          </div>
        ) : tools.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-400">
            No tools registered yet — click “Register Tool”.
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm text-zinc-600">
              <thead className="bg-zinc-50 text-xs font-semibold uppercase text-zinc-500">
                <tr>
                  <th className="px-4 py-3">Tool</th>
                  <th className="px-4 py-3">Category</th>
                  <th className="px-4 py-3">Method</th>
                  <th className="px-4 py-3">Scope</th>
                  <th className="px-4 py-3">Endpoint</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {tools.map((t) => (
                  <tr key={t.id} className="hover:bg-zinc-50/50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-900">{t.name}</div>
                      <div className="text-xs text-zinc-400">{t.description || "—"}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-700">
                        {t.category}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{t.method}</td>
                    <td className="px-4 py-3">
                      {t.is_global ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                          <Globe className="h-3 w-3" /> Global
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                          <Lock className="h-3 w-3" /> Granted
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-500">
                      {t.endpoint_url || <span className="text-zinc-400">none (simulated)</span>}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => embedMutation.mutate(t.id)}
                          className="p-1 text-zinc-400 hover:text-indigo-600 cursor-pointer"
                          title="(Re)compute semantic embedding"
                          disabled={embedMutation.isPending}
                        >
                          <Sparkles className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            setGrantTool(t);
                            setShowGrantModal(true);
                          }}
                          className="p-1 text-zinc-400 hover:text-sky-600 cursor-pointer"
                          title="Grant to tenant"
                        >
                          <Share2 className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Delete tool “${t.name}”? This revokes any tenant grants.`)) {
                              deleteMutation.mutate(t.id);
                            }
                          }}
                          className="p-1 text-zinc-400 hover:text-red-600 cursor-pointer"
                          title="Delete tool"
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

      {showAddModal && (
        <CreateToolModal
          onClose={() => setShowAddModal(false)}
          onSubmit={(vals) => createMutation.mutate(vals)}
          isPending={createMutation.isPending}
          error={
            createMutation.isError
              ? createMutation.error instanceof ApiError
                ? createMutation.error.message
                : "Failed to register tool"
              : null
          }
        />
      )}

      {showGrantModal && grantTool && (
        <GrantToolModal
          tool={grantTool}
          tenants={tenants}
          onClose={() => setShowGrantModal(false)}
          onSubmit={(vals) =>
            grantMutation.mutate({ tenant_id: vals.tenant_id, resource_id: grantTool.id })
          }
          isPending={grantMutation.isPending}
          error={
            grantMutation.isError
              ? grantMutation.error instanceof ApiError
                ? grantMutation.error.message
                : "Failed to grant resource"
              : null
          }
        />
      )}
    </ProtectedDashboard>
  );
}

function CreateToolModal({
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  onClose: () => void;
  onSubmit: (vals: CreateVendorToolBody) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("custom");
  const [method, setMethod] = useState("POST");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [isGlobal, setIsGlobal] = useState(false);
  const [paramsSchema, setParamsSchema] = useState('{\n  "type": "object",\n  "properties": {}\n}');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return;
    let parsed: Record<string, unknown> = {};
    try {
      parsed = paramsSchema.trim() ? JSON.parse(paramsSchema) : {};
    } catch {
      alert("parameters_schema must be valid JSON");
      return;
    }
    onSubmit({
      name,
      description,
      category,
      method,
      endpoint_url: endpointUrl || null,
      is_global: isGlobal,
      parameters_schema: parsed,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">Register Vendor Tool</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Tool name">
            <Input
              placeholder="finance.getInvoice"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </Field>
          <Field label="Description (used by the AI Compiler for semantic selection)">
            <Input
              placeholder="Retrieve a vendor invoice by id."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Category">
              <Input
                placeholder="finance"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              />
            </Field>
            <Field label="HTTP method">
              <select
                value={method}
                onChange={(e) => setMethod(e.target.value)}
                className="flex h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm focus-visible:ring-2 focus-visible:ring-zinc-900"
              >
                {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Endpoint URL (leave blank for a simulated/no-op tool)">
            <Input
              placeholder="https://api.example.com/invoices"
              value={endpointUrl}
              onChange={(e) => setEndpointUrl(e.target.value)}
            />
          </Field>
          <Field label="Parameters schema (JSON)">
            <textarea
              value={paramsSchema}
              onChange={(e) => setParamsSchema(e.target.value)}
              rows={5}
              className="flex w-full rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-xs focus-visible:ring-2 focus-visible:ring-zinc-900"
            />
          </Field>
          <label className="flex items-center gap-2 text-sm text-zinc-700">
            <input
              type="checkbox"
              checked={isGlobal}
              onChange={(e) => setIsGlobal(e.target.checked)}
              className="h-4 w-4 rounded border-zinc-300"
            />
            Global (available to all solo users without a tenant grant)
          </label>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : <Plus className="h-4 w-4 mr-1" />} Register
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function GrantToolModal({
  tool,
  tenants,
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  tool: VendorTool;
  tenants: VendorTenant[];
  onClose: () => void;
  onSubmit: (vals: { tenant_id: string }) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [tenantId, setTenantId] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!tenantId) return;
    onSubmit({ tenant_id: tenantId });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-3">
          <h3 className="text-lg font-semibold text-zinc-900">
            Grant “{tool.name}” to tenant
          </h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 cursor-pointer">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Tenant / Organization">
            <select
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              required
              className="flex h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm focus-visible:ring-2 focus-visible:ring-zinc-900"
            >
              <option value="" disabled>Select a tenant…</option>
              {tenants
                .filter((t) => !t.is_personal)
                .map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
            </select>
          </Field>
          <p className="text-xs text-zinc-500">
            All members of this tenant will inherit access to this tool.
          </p>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? <Spinner /> : <Share2 className="h-4 w-4 mr-1" />} Grant access
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}