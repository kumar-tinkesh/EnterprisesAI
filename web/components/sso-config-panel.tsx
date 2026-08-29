"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type SsoConfig } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Field } from "@/components/form-fields";

/** View / edit the tenant's SSO (OIDC) provider configuration. */
export function SsoConfigPanel() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();

  const [editing, setEditing] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [discoveryUrl, setDiscoveryUrl] = useState("");
  const [redirectUri, setRedirectUri] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const { data: config, isLoading } = useQuery({
    queryKey: ["sso-config", accessToken],
    queryFn: () => api.getSsoConfig(accessToken),
    enabled: !!accessToken,
    retry: false,
  });

  const saveMutation = useMutation({
    mutationFn: (body: {
      provider: string;
      client_id: string;
      client_secret: string;
      discovery_url: string;
      redirect_uri?: string;
      enabled?: boolean;
    }) => api.updateSsoConfig(accessToken, body),
    onSuccess: () => {
      setEditing(false);
      setFormError(null);
      setClientSecret("");
      queryClient.invalidateQueries({ queryKey: ["sso-config"] });
    },
  });

  const current = (config as SsoConfig | null | undefined) || null;

  if (isLoading) {
    return (
      <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-zinc-900">SSO Configuration</h2>
        <div className="mt-4 flex items-center gap-2 text-sm text-zinc-500">
          <Spinner className="h-4 w-4" /> Loading...
        </div>
      </div>
    );
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientId || !discoveryUrl) {
      setFormError("Client ID and Discovery URL are required.");
      return;
    }
    if (!current && !clientSecret) {
      setFormError("A Client Secret is required to create SSO config.");
      return;
    }
    saveMutation.mutate({
      provider: current?.provider || "google",
      client_id: clientId,
      client_secret: clientSecret,
      discovery_url: discoveryUrl,
      redirect_uri: redirectUri,
      enabled: true,
    });
  };

  return (
    <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-900">SSO Configuration</h2>
        {!editing && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setEditing(true);
              setClientId(current?.client_id || "");
              setDiscoveryUrl(current?.discovery_url || "");
              setRedirectUri(current?.redirect_uri || "");
              setFormError(null);
            }}
          >
            {current ? "Edit" : "Configure"}
          </Button>
        )}
      </div>

      {!editing ? (
        current ? (
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium text-zinc-400">Provider</dt>
              <dd className="mt-0.5 font-medium text-zinc-800">{current.provider}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-zinc-400">Status</dt>
              <dd className="mt-0.5">
                <span
                  className={
                    current.enabled
                      ? "rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700"
                      : "rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-500"
                  }
                >
                  {current.enabled ? "Enabled" : "Disabled"}
                </span>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-zinc-400">Client ID</dt>
              <dd className="mt-0.5 text-zinc-800">{current.client_id}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-zinc-400">Redirect URI</dt>
              <dd className="mt-0.5 break-all text-zinc-800">{current.redirect_uri}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs font-medium text-zinc-400">Discovery URL</dt>
              <dd className="mt-0.5 break-all text-zinc-800">{current.discovery_url}</dd>
            </div>
          </dl>
        ) : (
          <p className="mt-4 text-sm text-zinc-400">
            No SSO provider configured. Install Google or another OpenID Connect
            provider to enable single sign-on.
          </p>
        )
      ) : (
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <Field label="Client ID">
            <Input
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="xxxx.apps.googleusercontent.com"
              required
            />
          </Field>
          <Field label="Client Secret">
            <Input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder={current ? "Leave blank to keep unchanged" : "Required"}
              required={!current}
            />
          </Field>
          <Field label="Discovery URL">
            <Input
              value={discoveryUrl}
              onChange={(e) => setDiscoveryUrl(e.target.value)}
              placeholder="https://accounts.google.com/.well-known/openid-configuration"
              required
            />
          </Field>
          <Field label="Redirect URI">
            <Input
              value={redirectUri}
              onChange={(e) => setRedirectUri(e.target.value)}
              placeholder="http://localhost:3000/auth/callback"
            />
          </Field>

          {formError && <p className="text-xs text-red-600">{formError}</p>}
          {saveMutation.isError && (
            <p className="text-xs text-red-600">
              {saveMutation.error instanceof ApiError
                ? saveMutation.error.message
                : "Failed to save SSO configuration"}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setEditing(false);
                setFormError(null);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? <Spinner /> : "Save"}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

