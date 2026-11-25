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
    <main className="bg-ambient-grid relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-4 py-10 sm:py-16">
      <div className="pointer-events-none absolute top-1/4 left-1/2 h-80 w-80 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--accent)]/15 blur-[100px]" aria-hidden />
      <div className="animate-fade-up relative w-full max-w-sm sm:max-w-md">
        <div className="mb-8 flex items-center justify-center gap-2.5">
          <span className="animate-pulse-glow flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] text-white shadow-lg ring-1 ring-white/20">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="text-lg font-semibold tracking-tight text-zinc-100">EnterpriseAI</span>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[var(--surface)]/95 p-5 shadow-2xl ring-1 ring-white/5 backdrop-blur-md sm:p-8">
          <div role="tablist" aria-label="Log in or sign up" className="mb-6 grid grid-cols-2 gap-1 rounded-lg border border-white/5 bg-[var(--bg)] p-1">
            {(["login", "signup"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={cn(
                  "h-9 rounded-md text-sm font-medium transition-all duration-150 cursor-pointer",
                  mode === m
                    ? "bg-[var(--surface-strong)] text-[var(--text)] shadow-xs"
                    : "text-[var(--text-subtle)] hover:text-[var(--text)]",
                )}
              >
                {m === "login" ? "Log in" : "Sign up"}
              </button>
            ))}
          </div>

          <div key={mode} className="animate-fade-in">
            <h1 className="text-xl font-semibold tracking-tight">{COPY[mode].title}</h1>
            <p className="mt-1 mb-6 text-sm text-[var(--text-muted)]">{COPY[mode].sub}</p>

            {mode === "login" ? <LoginForm /> : <SignupForm />}
          </div>
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
