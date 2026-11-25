"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { afterLoginPath } from "@/lib/after-login";
import { useAuthStore } from "@/stores/auth-store";
import { Spinner } from "@/components/ui/spinner";
import { buttonVariants } from "@/components/ui/button";

function Waiting({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-3">
      <Spinner className="text-[var(--text-muted)]" />
      <p className="text-sm text-[var(--text-muted)]">{text}</p>
    </div>
  );
}

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const loginStore = useAuthStore((s) => s.login);

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function processCallback() {
      const code = searchParams.get("code");
      const state = searchParams.get("state") || "";
      const codeVerifier = sessionStorage.getItem("sso_code_verifier") || "";

      if (!code) {
        const errorDetail =
          searchParams.get("error_description") ||
          "Google didn't send a sign-in code back.";
        setError(errorDetail);
        if (window.opener && window.opener !== window) {
          window.opener.postMessage(
            { type: "GOOGLE_AUTH_ERROR", error: errorDetail },
            window.location.origin,
          );
          setTimeout(() => window.close(), 2000);
        }
        return;
      }

      try {
        const callbackRes = await api.ssoCallback(code, state, codeVerifier);
        sessionStorage.removeItem("sso_code_verifier");

        const user = await api.me(callbackRes.access_token);
        const payload = {
          access_token: callbackRes.access_token,
          refresh_token: callbackRes.refresh_token,
          token_type: callbackRes.token_type || "bearer",
          user,
        };

        // Opened as a popup: hand the session to the tab that opened it and close.
        if (window.opener && window.opener !== window) {
          window.opener.postMessage(
            { type: "GOOGLE_AUTH_SUCCESS", payload },
            window.location.origin,
          );
          window.close();
          return;
        }

        // Full-page redirect (popup was blocked).
        loginStore(payload);
        router.push(afterLoginPath(user.role));
      } catch (err) {
        const errMsg =
          err instanceof ApiError ? err.message : "We couldn't finish signing you in with Google.";
        setError(errMsg);

        if (window.opener && window.opener !== window) {
          window.opener.postMessage(
            { type: "GOOGLE_AUTH_ERROR", error: errMsg },
            window.location.origin,
          );
          setTimeout(() => window.close(), 2000);
        }
      }
    }

    processCallback();
  }, [searchParams, loginStore, router]);

  if (!error) return <Waiting text="Signing you in with Google…" />;

  return (
    <div className="flex flex-col items-center gap-4">
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--danger-wash)] text-[var(--danger)]">
        <AlertCircle className="h-5 w-5" />
      </span>
      <div className="space-y-1">
        <h1 className="text-base font-semibold">Google sign-in didn&apos;t work</h1>
        <p className="text-sm text-[var(--text-muted)]">{error}</p>
      </div>
      <Link href="/auth" className={buttonVariants({ className: "h-10 w-full" })}>
        Back to log in
      </Link>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <main className="bg-ambient-grid flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="animate-scale-in w-full max-w-sm rounded-2xl border border-white/10 bg-[var(--surface)]/95 p-6 text-center shadow-2xl ring-1 ring-white/5 backdrop-blur-md sm:p-8">
        <Suspense fallback={<Waiting text="Loading…" />}>
          <AuthCallbackContent />
        </Suspense>
      </div>
    </main>
  );
}
