"use client";

import { useEffect, useState } from "react";
import { Building2, ShieldCheck, Users } from "lucide-react";

import { LoginForm } from "@/components/login-form";
import { SignupForm } from "@/components/signup-form";
import { rememberNext } from "@/lib/after-login";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Mode = "login" | "signup";

export default function AuthPage() {
  const [mode, setMode] = useState<Mode>("login");

  // /auth?next=/r/abc&mode=signup — a share link sent them here; go back there after.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    rememberNext(params.get("next"));
    if (params.get("mode") === "signup") setMode("signup");
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col gap-6">
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-500/20">
            <Building2 className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-semibold">EnterpriseAI</h1>
          <p className="text-sm text-zinc-500">
            Vendor · Tenant · Workspace — one account, three dashboards
          </p>
        </div>

        <Card>
          <CardHeader>
            <div className="mb-2 grid grid-cols-2 gap-1 rounded-lg bg-zinc-100 p-1">
              {(["login", "signup"] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    "rounded-md py-2 text-sm font-medium capitalize transition-colors",
                    mode === m
                      ? "bg-white text-zinc-900 shadow-sm"
                      : "text-zinc-500 hover:text-zinc-800",
                  )}
                >
                  {m === "login" ? "Login" : "Sign up"}
                </button>
              ))}
            </div>
            <CardTitle className="text-lg">
              {mode === "login" ? "Welcome back" : "Create an account"}
            </CardTitle>
            <CardDescription>
              {mode === "login"
                ? "Log in and we'll take you to your dashboard."
                : "Pick a role to get the matching dashboard."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {mode === "login" ? <LoginForm /> : <SignupForm />}
          </CardContent>
        </Card>

        <div className="flex items-center justify-center gap-4 text-xs text-zinc-500">
          <span className="flex items-center gap-1"><ShieldCheck className="h-3.5 w-3.5" /> Vendor</span>
          <span className="flex items-center gap-1"><Users className="h-3.5 w-3.5" /> Tenant</span>
          <span className="flex items-center gap-1"><Building2 className="h-3.5 w-3.5" /> Workspace</span>
        </div>
      </div>
    </main>
  );
}