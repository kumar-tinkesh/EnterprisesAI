"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { dashboardPathForRole } from "@/lib/validations";
import { useAuthStore } from "@/stores/auth-store";
import { Spinner } from "@/components/ui/spinner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
          "No authorization code returned from provider.";
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

        // If opened inside a Popup window, post message to parent tab and close popup
        if (window.opener && window.opener !== window) {
          window.opener.postMessage(
            { type: "GOOGLE_AUTH_SUCCESS", payload },
            window.location.origin,
          );
          window.close();
          return;
        }

        // Fallback for full-page redirect
        loginStore(payload);
        router.push(dashboardPathForRole(user.role));
      } catch (err) {
        const errMsg =
          err instanceof ApiError ? err.message : "SSO Callback verification failed";
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

  return (
    <CardContent className="flex flex-col items-center justify-center gap-4 py-8">
      {error ? (
        <div className="space-y-4">
          <p className="text-sm text-red-600">{error}</p>
          <button
            type="button"
            onClick={() => router.push("/auth")}
            className="text-xs font-medium text-zinc-900 underline"
          >
            Back to Login
          </button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <Spinner />
          <p className="text-sm text-zinc-500">Exchanging credentials...</p>
        </div>
      )}
    </CardContent>
  );
}

export default function AuthCallbackPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <CardTitle>Completing Google Login...</CardTitle>
        </CardHeader>
        <Suspense
          fallback={
            <CardContent className="flex flex-col items-center justify-center gap-3 py-8">
              <Spinner />
              <p className="text-sm text-zinc-500">Loading...</p>
            </CardContent>
          }
        >
          <AuthCallbackContent />
        </Suspense>
      </Card>
    </main>
  );
}
