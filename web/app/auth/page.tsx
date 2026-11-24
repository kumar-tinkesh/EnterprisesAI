"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

import { LoginForm } from "@/components/login-form";
import { SignupForm } from "@/components/signup-form";
import { rememberNext } from "@/lib/after-login";
import { cn } from "@/lib/utils";

type Mode = "login" | "signup";

const COPY: Record<Mode, { title: string; sub: string }> = {
  login: { title: "Welcome back", sub: "Log in to your workspace." },
  signup: { title: "Create your account", sub: "Free to start. Build your first agent in minutes." },
};

export default function AuthPage() {
  const [mode, setMode] = useState<Mode>("login");

  // /auth?next=/r/abc&mode=signup — a share link sent them here; go back there after.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    rememberNext(params.get("next"));
    if (params.get("mode") === "signup") setMode("signup");
  }, []);

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 py-10 sm:py-16">
      <div className="w-full max-w-sm sm:max-w-md">
        <div className="mb-8 flex items-center justify-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-white">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="text-base font-semibold tracking-tight">EnterpriseAI</span>
        </div>

        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:p-8">
          <div role="tablist" aria-label="Log in or sign up" className="mb-6 grid grid-cols-2 gap-1 rounded-lg bg-[var(--bg)] p-1">
            {(["login", "signup"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={cn(
                  "h-9 rounded-md text-sm font-medium transition-colors cursor-pointer",
                  mode === m
                    ? "bg-[var(--surface-strong)] text-[var(--text)]"
                    : "text-[var(--text-subtle)] hover:text-[var(--text)]",
                )}
              >
                {m === "login" ? "Log in" : "Sign up"}
              </button>
            ))}
          </div>

          <h1 className="text-xl font-semibold tracking-tight">{COPY[mode].title}</h1>
          <p className="mt-1 mb-6 text-sm text-[var(--text-muted)]">{COPY[mode].sub}</p>

          {mode === "login" ? <LoginForm /> : <SignupForm />}
        </div>

        <p className="mt-6 text-center text-sm text-[var(--text-subtle)]">
          {mode === "login" ? "New here? " : "Already have an account? "}
          <button
            type="button"
            onClick={() => setMode(mode === "login" ? "signup" : "login")}
            className="font-medium text-[var(--link)] hover:underline cursor-pointer"
          >
            {mode === "login" ? "Create an account" : "Log in"}
          </button>
        </p>
      </div>
    </main>
  );
}
