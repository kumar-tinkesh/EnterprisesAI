"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuthStore } from "@/stores/auth-store";
import { roleForDashboard } from "@/lib/validations";
import { api } from "@/lib/api";
import { Spinner } from "@/components/ui/spinner";

/**
 * Client-side route guard. Renders children only when the stored access
 * token's role matches the role required by the dashboard at ``path``.
 * Otherwise redirects to /auth (not signed in) or shows "forbidden".
 */
export default function ProtectedDashboard({
  path,
  title,
  description,
  children,
}: {
  path: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let isMounted = true;
    async function validateToken() {
      if (!accessToken || !user) {
        if (isMounted) setChecked(true);
        return;
      }
      try {
        await api.me(accessToken);
      } catch {
        // Token expired or invalid -> logout and redirect
        logout();
        router.replace("/auth");
        return;
      }
      if (isMounted) setChecked(true);
    }
    validateToken();
    return () => {
      isMounted = false;
    };
  }, [accessToken, user, logout, router]);

  if (!checked) {
    return (
      <Centered>
        <Spinner className="h-8 w-8 text-zinc-500" />
      </Centered>
    );
  }

  if (!accessToken || !user) {
    router.replace("/auth");
    return null;
  }

  const required = roleForDashboard(path);
  const allowed = Array.isArray(required)
    ? required.includes(user.role)
    : user.role === required;

  if (!allowed) {
    return (
      <Centered>
        <h1 className="text-2xl font-semibold">Access denied</h1>
        <p className="text-zinc-500">Your role does not grant access to this dashboard.</p>
        <button
          onClick={() => {
            logout();
            router.replace("/auth");
          }}
          className="mt-4 text-sm underline cursor-pointer"
        >
          Sign out
        </button>
      </Centered>
    );
  }

  return (
    <div className="mx-auto max-w-6xl p-6">
      <header className="flex items-center justify-between border-b border-zinc-200 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">{title}</h1>
          <p className="text-sm text-zinc-500">{description}</p>
        </div>
        <button
          onClick={() => {
            logout();
            router.replace("/auth");
          }}
          className="text-sm font-medium text-zinc-600 hover:text-zinc-900 cursor-pointer"
        >
          Sign out ({user.email})
        </button>
      </header>
      {children}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-2">
      {children}
    </div>
  );
}