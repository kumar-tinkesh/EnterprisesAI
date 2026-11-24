"use client";

import { useState } from "react";
import {
  Building2,
  Check,
  CheckCircle2,
  Globe,
  Key,
  Lock,
  Plus,
  Save,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Trash2,
  Users,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

export default function TenantSettingsPage() {
  const user = useAuthStore((s) => s.user);

  const [orgName, setOrgName] = useState("Enterprise AI Corp");
  const [orgDomain, setOrgDomain] = useState("enterpriseai.com");
  const [ssoProvider, setSsoProvider] = useState<"google" | "okta" | "azure" | "saml">("okta");
  const [enforce2FA, setEnforce2FA] = useState(true);
  const [sessionTimeoutHours, setSessionTimeoutHours] = useState(24);
  const [saved, setSaved] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <ProtectedDashboard
      path="/tenant"
      title="Security & SSO Settings"
      description="Configure enterprise Single Sign-On, authentication security, and domain policies."
      action={
        <div className="flex items-center gap-2">
          {saved && (
            <span className="flex items-center gap-1.5 text-xs text-emerald-400">
              <Check className="h-3.5 w-3.5" /> Policies Updated
            </span>
          )}
          <Button onClick={handleSave}>
            <Save className="h-4 w-4" /> Save Policies
          </Button>
        </div>
      }
    >
      <div className="mt-6 space-y-6 max-w-4xl">
        {/* Organization Identity */}
        <section className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-4">
          <div>
            <h2 className="text-base font-semibold text-zinc-100">Organization Profile</h2>
            <p className="text-xs text-zinc-400">Primary legal entity and authorized email domains.</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-zinc-300 mb-1.5">Organization Name</label>
              <Input
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                placeholder="Company Name"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-300 mb-1.5">Primary Verified Domain</label>
              <div className="relative">
                <Globe className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                <Input
                  className="pl-9"
                  value={orgDomain}
                  onChange={(e) => setOrgDomain(e.target.value)}
                  placeholder="company.com"
                />
              </div>
            </div>
          </div>
        </section>

        {/* Enterprise SSO / OIDC Identity Provider */}
        <section className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-5">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-base font-semibold text-zinc-100">Single Sign-On (SSO / SAML 2.0)</h2>
              <p className="text-xs text-zinc-400">Enforce corporate identity provider for all member logins.</p>
            </div>
            <span className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" /> OIDC Connected
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            {[
              { id: "google", label: "Google Workspace", desc: "OAuth 2.0 PKCE" },
              { id: "okta", label: "Okta Workforce", desc: "SAML 2.0 / OIDC" },
              { id: "azure", label: "Microsoft Entra ID", desc: "Azure AD SSO" },
              { id: "saml", label: "Custom SAML 2.0", desc: "Metadata XML / IdP" },
            ].map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setSsoProvider(p.id as any)}
                className={cn(
                  "rounded-xl border p-4 text-left transition-all cursor-pointer",
                  ssoProvider === p.id
                    ? "border-[var(--accent)] bg-white/[0.06] ring-1 ring-[var(--accent)]"
                    : "border-white/10 bg-white/[0.02] hover:border-white/20",
                )}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-semibold text-zinc-200">{p.label}</span>
                  {ssoProvider === p.id && <Check className="h-3.5 w-3.5 text-[var(--link)]" />}
                </div>
                <p className="text-[11px] text-zinc-500">{p.desc}</p>
              </button>
            ))}
          </div>

          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4 text-xs space-y-2">
            <p className="font-medium text-zinc-200">ACS / Redirect Callback URL</p>
            <code className="block rounded bg-black/40 p-2 font-mono text-[11px] text-zinc-300 select-all">
              https://api.enterpriseai.internal/api/v1/sso/callback
            </code>
            <p className="text-[11px] text-zinc-500">
              Provide this Assertion Consumer Service (ACS) endpoint inside your IdP application settings.
            </p>
          </div>
        </section>

        {/* Security & Access Policies */}
        <section className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-4">
          <div>
            <h2 className="text-base font-semibold text-zinc-100">Security & Compliance Policies</h2>
            <p className="text-xs text-zinc-400">Strict organizational controls for enterprise compliance.</p>
          </div>

          <div className="space-y-4 pt-1">
            <div className="flex items-start justify-between gap-4 py-2 border-b border-white/5">
              <div>
                <p className="text-sm font-medium text-zinc-200">Enforce Mandatory Two-Factor Authentication</p>
                <p className="text-xs text-zinc-500">Require all members to register an authenticator app before accessing workspace agents.</p>
              </div>
              <input
                type="checkbox"
                checked={enforce2FA}
                onChange={(e) => setEnforce2FA(e.target.checked)}
                className="h-4 w-4 rounded border-zinc-700 text-indigo-600 focus:ring-indigo-500"
              />
            </div>

            <div className="flex items-center justify-between gap-4 py-2">
              <div>
                <p className="text-sm font-medium text-zinc-200">Session Idle Timeout</p>
                <p className="text-xs text-zinc-500">Automatically revoke access tokens after inactivity.</p>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={1}
                  max={72}
                  className="w-20 text-center"
                  value={sessionTimeoutHours}
                  onChange={(e) => setSessionTimeoutHours(parseInt(e.target.value) || 24)}
                />
                <span className="text-xs text-zinc-400">Hours</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </ProtectedDashboard>
  );
}
