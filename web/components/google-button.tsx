"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { dashboardPathForRole } from "@/lib/validations";
import { useAuthStore } from "@/stores/auth-store";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export function GoogleButton() {
  const router = useRouter();
  const loginStore = useAuthStore((s) => s.login);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;

      if (event.data?.type === "GOOGLE_AUTH_SUCCESS") {
        setLoading(false);
        const payload = event.data.payload;
        loginStore(payload);
        router.push(dashboardPathForRole(payload.user.role));
      } else if (event.data?.type === "GOOGLE_AUTH_ERROR") {
        setLoading(false);
        setError(event.data.error || "Google authentication failed");
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [loginStore, router]);

  const handleGoogleAuth = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.ssoInitiate();
      if (res.code_verifier) {
        sessionStorage.setItem("sso_code_verifier", res.code_verifier);
      }

      // Calculate center position for popup window
      const width = 500;
      const height = 600;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;

      const popup = window.open(
        res.authorization_url,
        "google_oauth_popup",
        `width=${width},height=${height},top=${top},left=${left},status=no,menubar=no,toolbar=no`,
      );

      if (!popup) {
        // Fallback to window redirect if popup was blocked by browser
        window.location.href = res.authorization_url;
        return;
      }

      // Check if user manually closes popup window before completing auth
      const timer = setInterval(() => {
        if (popup.closed) {
          clearInterval(timer);
          setLoading(false);
        }
      }, 600);
    } catch (err) {
      setLoading(false);
      setError(
        err instanceof ApiError ? err.message : "Failed to initiate Google login",
      );
    }
  };

  return (
    <div className="w-full space-y-2">
      <Button
        type="button"
        variant="outline"
        onClick={handleGoogleAuth}
        disabled={loading}
        className="w-full border-zinc-300 hover:bg-zinc-50"
      >
        {loading ? (
          <Spinner />
        ) : (
          <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
            <path
              fill="#4285F4"
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
            />
            <path
              fill="#34A853"
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
            />
            <path
              fill="#FBBC05"
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
            />
            <path
              fill="#EA4335"
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
            />
          </svg>
        )}
        Continue with Google
      </Button>
      {error && <p className="text-xs text-red-600 text-center">{error}</p>}
    </div>
  );
}
