"use client";

/**
 * Minimal typed API client for the EnterpriseAI auth backend.
 * Auth is handled server-side by the backend (JWT); we pass the bearer
 * token along on protected calls.
 */

import type { AuthPayload, Role } from "@/lib/validations";
import { useAuthStore } from "@/stores/auth-store";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * Best-effort silent token refresh using the persisted refresh token.
 * Returns the new access token, or null if there is nothing to refresh with.
 */
async function tryRefreshToken(): Promise<string | null> {
  const store = useAuthStore.getState();
  const refreshToken = store.refreshToken;
  if (!refreshToken) return null;

  const res = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    store.logout();
    return null;
  }
  const data = await res.json();
  store.login({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    token_type: data.token_type || "bearer",
    user: store.user!,
  });
  return data.access_token;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res = await fetch(`${API_URL}${path}`, { ...init, headers });

  // On an expired/revoked access token, try a silent refresh once, then retry.
  if (res.status === 401 && token) {
    const fresh = await tryRefreshToken();
    if (fresh) {
      headers.Authorization = `Bearer ${fresh}`;
      res = await fetch(`${API_URL}${path}`, { ...init, headers });
    }
  }

  if (!res.ok) {
    let detail: string = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* ignore parse errors */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return {} as T;
  return (await res.json()) as T;
}

interface SignupBody {
  email: string;
  password: string;
  full_name: string;
  role: string;
  tenant_name: string;
}

export interface MeResponse {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  tenant_id: string | null;
  is_active: boolean;
}

export interface TenantStats {
  workspace_count: number;
  member_count: number;
}

export interface TenantMember {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface CreateMemberBody {
  email: string;
  password: string;
  full_name: string;
  role?: string;
}

export interface UpdateMemberBody {
  full_name?: string;
  role?: string;
  is_active?: boolean;
  password?: string;
}

export interface VendorStats {
  total_tenants: number;
  individual_users: number;
  total_users: number;
  total_workspaces: number;
}

export interface VendorTenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  is_personal: boolean;
  created_at: string;
  admin_email: string | null;
  admin_name: string | null;
  user_count: number;
  workspace_count: number;
}

export interface CreateVendorTenantBody {
  name: string;
  slug?: string;
  admin_email: string;
  admin_full_name: string;
  admin_password: string;
}

export interface UpdateVendorTenantBody {
  name?: string;
  status?: string;
}

export interface SsoInitiateResponse {
  authorization_url: string;
  state: string;
  code_verifier?: string;
}

export interface SsoCallbackResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user_id: string;
}

export interface AuditLog {
  id: string;
  action: string;
  resource: string;
  detail: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string | null;
}

export interface DashboardResponse {
  dashboard: string;
  role: string;
  message: string;
}

export const api = {
  login: (body: { email: string; password: string; role?: string }) =>
    request<AuthPayload>("/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  signup: (body: SignupBody) =>
    request<AuthPayload>("/auth/signup", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  me: (token: string) => request<MeResponse>("/auth/me", { method: "GET" }, token),

  // SSO / Google Auth endpoints for solo_user
  ssoInitiate: () =>
    request<SsoInitiateResponse>("/sso/initiate", { method: "GET" }),
  ssoCallback: (code: string, state: string, codeVerifier: string) =>
    request<SsoCallbackResponse>(
      `/sso/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}&code_verifier=${encodeURIComponent(codeVerifier)}`,
      { method: "GET" },
    ),

  // Tenant Admin endpoints
  getTenantStats: (token: string) =>
    request<TenantStats>("/tenant/stats", { method: "GET" }, token),
  getTenantMembers: (token: string) =>
    request<TenantMember[]>("/tenant/members", { method: "GET" }, token),
  createTenantMember: (token: string, body: CreateMemberBody) =>
    request<TenantMember>("/tenant/members", {
      method: "POST",
      body: JSON.stringify(body),
    }, token),
  updateTenantMember: (token: string, memberId: string, body: UpdateMemberBody) =>
    request<TenantMember>(`/tenant/members/${memberId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }, token),
  deleteTenantMember: (token: string, memberId: string) =>
    request<void>(`/tenant/members/${memberId}`, { method: "DELETE" }, token),

  // Vendor Admin endpoints
  getVendorStats: (token: string) =>
    request<VendorStats>("/vendor/stats", { method: "GET" }, token),
  getVendorTenants: (token: string) =>
    request<VendorTenant[]>("/vendor/tenants", { method: "GET" }, token),
  createVendorTenant: (token: string, body: CreateVendorTenantBody) =>
    request<VendorTenant>("/vendor/tenants", {
      method: "POST",
      body: JSON.stringify(body),
    }, token),
  updateVendorTenant: (token: string, tenantId: string, body: UpdateVendorTenantBody) =>
    request<VendorTenant>(`/vendor/tenants/${tenantId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }, token),
  deleteVendorTenant: (token: string, tenantId: string) =>
    request<void>(`/vendor/tenants/${tenantId}`, { method: "DELETE" }, token),

  // Audit logs (scoped by role server-side)
  getAuditLogs: (token: string, params?: { action?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.action) qs.set("action", params.action);
    if (params?.limit) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return request<AuditLog[]>(`/auth/audit-logs${query ? `?${query}` : ""}`, {
      method: "GET",
    }, token);
  },

  // Role-scoped dashboard endpoint (server-side access validation)
  getDashboard: (token: string, dashboard: "vendor" | "tenant" | "user" | "workspace") =>
    request<DashboardResponse>(`/dashboard/${dashboard}`, { method: "GET" }, token),
};
