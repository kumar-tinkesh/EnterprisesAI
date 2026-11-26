"use client";

/**
 * Workspaces (auth service, /api/v1/workspaces).
 *
 * A solo account has exactly one workspace and never sees any of this.
 * A tenant admin creates workspaces and decides who is in them; a tenant
 * user sees the ones they're in and switches between them. Switching gets a
 * new token for that workspace — every agent, workflow, chat and run the app
 * then shows is that workspace's — so all cached data is dropped.
 */

import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { request } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import type { AuthPayload } from "@/lib/validations";

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string;
  status: "active" | "archived";
  my_role: "admin" | "member";
  is_member: boolean;
  member_count: number;
  is_current: boolean;
  created_at: string;
}

export interface WorkspaceList {
  workspaces: Workspace[];
  current_id: string | null;
  can_create: boolean;
  can_switch: boolean;
}

export interface WorkspaceMember {
  user_id: string;
  email: string;
  full_name: string;
  tenant_role: string;
  role: "admin" | "member";
  is_active: boolean;
  added_at: string;
}

const W = "/workspaces";

export const workspacesApi = {
  list: (t: string, includeArchived = false) =>
    request<WorkspaceList>(`${W}${includeArchived ? "?include_archived=true" : ""}`, {}, t),
  create: (t: string, body: { name: string; description?: string }) =>
    request<Workspace>(W, { method: "POST", body: JSON.stringify(body) }, t),
  update: (t: string, id: string, body: { name?: string; description?: string; status?: "active" | "archived" }) =>
    request<Workspace>(`${W}/${id}`, { method: "PATCH", body: JSON.stringify(body) }, t),
  members: (t: string, id: string) => request<WorkspaceMember[]>(`${W}/${id}/members`, {}, t),
  addMember: (t: string, id: string, userId: string, role: "admin" | "member" = "member") =>
    request<WorkspaceMember[]>(`${W}/${id}/members`, { method: "POST", body: JSON.stringify({ user_id: userId, role }) }, t),
  setRole: (t: string, id: string, userId: string, role: "admin" | "member") =>
    request<WorkspaceMember[]>(`${W}/${id}/members/${userId}`, { method: "PATCH", body: JSON.stringify({ role }) }, t),
  removeMember: (t: string, id: string, userId: string) =>
    request<void>(`${W}/${id}/members/${userId}`, { method: "DELETE" }, t),
  switchTo: (t: string, id: string) => request<AuthPayload>(`${W}/${id}/switch`, { method: "POST" }, t),
};

/** The person's workspaces. Off for solo accounts (they have exactly one). */
export function useWorkspaces(includeArchived = false) {
  const token = useAuthStore((s) => s.accessToken) || "";
  const role = useAuthStore((s) => s.user?.role);
  const team = role === "tenant_user" || role === "tenant_admin";
  return useQuery({
    queryKey: ["workspaces", includeArchived],
    queryFn: () => workspacesApi.list(token, includeArchived),
    enabled: !!token && team,
    staleTime: 30_000,
  });
}

/** Switch workspace: new token, forget every cached answer, back to the dashboard. */
export function useSwitchWorkspace() {
  const login = useAuthStore((s) => s.login);
  const client = useQueryClient();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const switchTo = useCallback(
    async (id: string, { stay = false }: { stay?: boolean } = {}) => {
      const token = useAuthStore.getState().accessToken || "";
      setBusy(id);
      setError(null);
      try {
        const payload = await workspacesApi.switchTo(token, id);
        login(payload);
        client.clear();
        if (!stay) router.push("/user");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't switch workspace.");
      } finally {
        setBusy(null);
      }
    },
    [client, login, router],
  );

  return { switchTo, busy, error };
}
