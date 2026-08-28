"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { Account, AuthPayload, Role } from "@/lib/validations";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: Account | null;
  login: (payload: AuthPayload) => void;
  logout: () => void;
  role: () => Role | null;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,

      login: (payload) =>
        set({
          accessToken: payload.access_token,
          refreshToken: payload.refresh_token,
          user: payload.user,
        }),

      logout: () =>
        set({ accessToken: null, refreshToken: null, user: null }),

      role: () => get().user?.role ?? null,
    }),
    {
      name: "auth-storage",
      partialize: (s) => ({
        accessToken: s.accessToken,
        refreshToken: s.refreshToken,
        user: s.user,
      }),
    },
  ),
);