"use client";

import { useState } from "react";
import {
  Bell,
  Check,
  Copy,
  Eye,
  EyeOff,
  Key,
  Laptop,
  Lock,
  Moon,
  Palette,
  Plus,
  Shield,
  Smartphone,
  Sun,
  Trash2,
  User,
} from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar } from "@/components/builder/chat/chat-message";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

type SettingsTab = "profile" | "appearance" | "security" | "api_keys" | "notifications";

interface PersonalToken {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used: string;
}

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const [tab, setTab] = useState<SettingsTab>("profile");

  // Profile Form state
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [profileSaved, setProfileSaved] = useState(false);

  // Appearance state
  const [themeTone, setThemeTone] = useState<"calm_dark" | "midnight" | "zinc">("calm_dark");
  const [compactDensity, setCompactDensity] = useState(false);
  const [animationsOn, setAnimationsOn] = useState(true);

  // Password state
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [passwordSaved, setPasswordSaved] = useState(false);

  // 2FA state
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);

  // API Tokens state
  const [tokens, setTokens] = useState<PersonalToken[]>([
    {
      id: "pat_1",
      name: "CLI Local Machine",
      prefix: "eai_pat_9a4f...",
      created_at: "2026-10-15",
      last_used: "Today",
    },
    {
      id: "pat_2",
      name: "GitHub Action CI/CD",
      prefix: "eai_pat_11b7...",
      created_at: "2026-11-01",
      last_used: "2 days ago",
    },
  ]);
  const [newTokenName, setNewTokenName] = useState("");
  const [justCreatedToken, setJustCreatedToken] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);

  // Notifications state
  const [notifyOnFail, setNotifyOnFail] = useState(true);
  const [notifyOnApproval, setNotifyOnApproval] = useState(true);
  const [weeklyDigest, setWeeklyDigest] = useState(true);

  const handleSaveProfile = (e: React.FormEvent) => {
    e.preventDefault();
    setProfileSaved(true);
    setTimeout(() => setProfileSaved(false), 2500);
  };

  const handleSavePassword = (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordSaved(true);
    setOldPassword("");
    setNewPassword("");
    setTimeout(() => setPasswordSaved(false), 2500);
  };

  const handleCreateToken = () => {
    if (!newTokenName.trim()) return;
    const rawKey = `eai_pat_${Math.random().toString(36).substring(2, 10)}${Math.random().toString(36).substring(2, 10)}`;
    const created: PersonalToken = {
      id: `pat_${Date.now()}`,
      name: newTokenName.trim(),
      prefix: `${rawKey.substring(0, 12)}...`,
      created_at: "Just now",
      last_used: "Never",
    };
    setTokens([created, ...tokens]);
    setJustCreatedToken(rawKey);
    setNewTokenName("");
  };

  const handleRevokeToken = (id: string) => {
    setTokens(tokens.filter((t) => t.id !== id));
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 2000);
  };

  const TABS = [
    { id: "profile" as const, label: "Profile", Icon: User },
    { id: "appearance" as const, label: "Appearance", Icon: Palette },
    { id: "security" as const, label: "Security & 2FA", Icon: Shield },
    { id: "api_keys" as const, label: "API Keys", Icon: Key },
    { id: "notifications" as const, label: "Notifications", Icon: Bell },
  ];

  return (
    <ProtectedDashboard
      path="/user"
      title="Settings"
      description="Manage your profile, theme, security keys, and alert preferences."
    >
      <div className="mt-6 flex flex-col gap-6 lg:flex-row">
        {/* Settings Navigation Sidebar */}
        <aside className="w-full shrink-0 lg:w-56">
          <nav className="flex flex-row gap-1 overflow-x-auto pb-2 lg:flex-col lg:pb-0" aria-label="Settings sub-navigation">
            {TABS.map(({ id, label, Icon }) => {
              const active = tab === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => setTab(id)}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors cursor-pointer text-left whitespace-nowrap",
                    active
                      ? "bg-[var(--surface-strong)] text-[var(--text)] font-semibold shadow-xs"
                      : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200",
                  )}
                >
                  <Icon className={cn("h-4 w-4", active ? "text-[var(--link)]" : "text-zinc-500")} />
                  <span>{label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Tab Content Panes */}
        <div className="flex-1 min-w-0">
          {/* 1. Profile Tab */}
          {tab === "profile" && (
            <div className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-6">
              <div>
                <h2 className="text-base font-semibold text-zinc-100">Personal Information</h2>
                <p className="text-xs text-zinc-400">Update your name and personal details displayed across workspace.</p>
              </div>

              <div className="flex items-center gap-4 py-2 border-y border-white/5">
                <Avatar name={fullName || user?.email || "User"} size={52} />
                <div>
                  <p className="text-sm font-medium text-zinc-200">{fullName || user?.email}</p>
                  <p className="text-xs text-zinc-500 capitalize">{user?.role?.replace("_", " ")}</p>
                </div>
              </div>

              <form onSubmit={handleSaveProfile} className="space-y-4 max-w-md">
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">Full Name</label>
                  <Input
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Abhishek Kumar"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">Email Address</label>
                  <Input
                    value={user?.email || ""}
                    disabled
                    className="opacity-70 cursor-not-allowed bg-white/[0.02]"
                  />
                  <p className="mt-1 text-[11px] text-zinc-500">Email is tied to your organization auth and cannot be changed here.</p>
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">Role & Scope</label>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-medium text-zinc-300 uppercase">
                      {user?.role || "user"}
                    </span>
                    <span className="text-xs text-zinc-500">
                      Tenant ID: {user?.tenant_id ? user.tenant_id.slice(0, 12) + "..." : "Personal"}
                    </span>
                  </div>
                </div>

                <div className="pt-2 flex items-center gap-3">
                  <Button type="submit">Save Changes</Button>
                  {profileSaved && (
                    <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                      <Check className="h-3.5 w-3.5" /> Saved successfully
                    </span>
                  )}
                </div>
              </form>
            </div>
          )}

          {/* 2. Appearance Tab */}
          {tab === "appearance" && (
            <div className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-6">
              <div>
                <h2 className="text-base font-semibold text-zinc-100">Theme & Workspace Styling</h2>
                <p className="text-xs text-zinc-400">Customize the visual tone, contrast, and layout density.</p>
              </div>

              <div className="space-y-3">
                <label className="block text-xs font-medium text-zinc-300">Color Palette</label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {[
                    { id: "calm_dark", label: "Calm Dark", desc: "Default neutral dark with indigo accent", border: "#4f46e5" },
                    { id: "midnight", label: "Deep Midnight", desc: "High contrast pure black & violet", border: "#8b5cf6" },
                    { id: "zinc", label: "Graphite Zinc", desc: "Subtle cool grey with emerald touch", border: "#10b981" },
                  ].map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setThemeTone(t.id as any)}
                      className={cn(
                        "rounded-xl border p-4 text-left transition-all cursor-pointer relative",
                        themeTone === t.id
                          ? "border-[var(--accent)] bg-white/[0.06] ring-1 ring-[var(--accent)]"
                          : "border-white/10 bg-white/[0.02] hover:border-white/20",
                      )}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="h-3.5 w-3.5 rounded-full" style={{ backgroundColor: t.border }} />
                        {themeTone === t.id && <Check className="h-3.5 w-3.5 text-[var(--link)]" />}
                      </div>
                      <p className="text-sm font-semibold text-zinc-200">{t.label}</p>
                      <p className="text-xs text-zinc-400 mt-1">{t.desc}</p>
                    </button>
                  ))}
                </div>
              </div>

              <div className="border-t border-white/5 pt-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Compact Density</p>
                    <p className="text-xs text-zinc-500">Reduces margins and padding in tables and graph nodes.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={compactDensity}
                    onChange={(e) => setCompactDensity(e.target.checked)}
                    className="h-4 w-4 rounded border-zinc-700 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Fluid Canvas Animations</p>
                    <p className="text-xs text-zinc-500">Show live edge flow particles and streaming text shimmer.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={animationsOn}
                    onChange={(e) => setAnimationsOn(e.target.checked)}
                    className="h-4 w-4 rounded border-zinc-700 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>
              </div>
            </div>
          )}

          {/* 3. Security & 2FA Tab */}
          {tab === "security" && (
            <div className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-6">
              <div>
                <h2 className="text-base font-semibold text-zinc-100">Security & Authentication</h2>
                <p className="text-xs text-zinc-400">Keep your account protected with Argon2id passwords and two-factor auth.</p>
              </div>

              {/* Password update */}
              <form onSubmit={handleSavePassword} className="space-y-4 max-w-md">
                <h3 className="text-sm font-semibold text-zinc-200">Change Password</h3>
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">Current Password</label>
                  <div className="relative">
                    <Input
                      type={showPassword ? "text" : "password"}
                      value={oldPassword}
                      onChange={(e) => setOldPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-200"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">New Password</label>
                  <Input
                    type={showPassword ? "text" : "password"}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Minimum 8 characters"
                    minLength={8}
                    required
                  />
                </div>

                <div className="flex items-center gap-3">
                  <Button type="submit">Update Password</Button>
                  {passwordSaved && (
                    <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                      <Check className="h-3.5 w-3.5" /> Password updated!
                    </span>
                  )}
                </div>
              </form>

              {/* Two Factor Auth */}
              <div className="border-t border-white/5 pt-5 space-y-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-zinc-200">Two-Factor Authentication (2FA)</h3>
                    <p className="text-xs text-zinc-400 mt-0.5">
                      Protect your account using an authenticator app (Google Authenticator, 1Password, Authy).
                    </p>
                  </div>
                  <Button
                    variant={twoFactorEnabled ? "outline" : "default"}
                    size="sm"
                    onClick={() => setTwoFactorEnabled(!twoFactorEnabled)}
                  >
                    {twoFactorEnabled ? "Disable 2FA" : "Enable 2FA"}
                  </Button>
                </div>
              </div>

              {/* Active Sessions */}
              <div className="border-t border-white/5 pt-5">
                <h3 className="text-sm font-semibold text-zinc-200 mb-3">Active Sessions</h3>
                <div className="space-y-2">
                  <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/[0.02] p-3 text-xs">
                    <div className="flex items-center gap-3">
                      <Laptop className="h-4 w-4 text-emerald-400" />
                      <div>
                        <p className="font-medium text-zinc-200">Current Session · Linux (Chrome 130)</p>
                        <p className="text-zinc-500">IP: 192.168.1.100 · Active now</p>
                      </div>
                    </div>
                    <span className="rounded bg-emerald-500/10 px-2 py-0.5 font-medium text-emerald-400">This Device</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 4. API Keys Tab */}
          {tab === "api_keys" && (
            <div className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-6">
              <div>
                <h2 className="text-base font-semibold text-zinc-100">Personal Access Tokens</h2>
                <p className="text-xs text-zinc-400">Use these tokens to authenticate via CLI, SDK, or external automated scripts.</p>
              </div>

              {/* New Token Banner if just created */}
              {justCreatedToken && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 space-y-2">
                  <p className="text-xs font-semibold text-emerald-400">
                    Token generated! Copy it now; you won&apos;t be able to see it again.
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 rounded bg-black/40 px-3 py-1.5 font-mono text-xs text-emerald-200 truncate">
                      {justCreatedToken}
                    </code>
                    <Button
                      size="sm"
                      onClick={() => copyToClipboard(justCreatedToken)}
                      className="shrink-0"
                    >
                      {copiedToken ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                      {copiedToken ? "Copied" : "Copy"}
                    </Button>
                  </div>
                </div>
              )}

              {/* Create new token input */}
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <Input
                  value={newTokenName}
                  onChange={(e) => setNewTokenName(e.target.value)}
                  placeholder="e.g. VSCode CLI, Production Runner"
                  className="flex-1"
                />
                <Button onClick={handleCreateToken} className="shrink-0">
                  <Plus className="h-4 w-4" /> Generate Token
                </Button>
              </div>

              {/* Token list */}
              <div className="divide-y divide-white/5 rounded-lg border border-white/10 overflow-hidden">
                {tokens.map((t) => (
                  <div key={t.id} className="flex items-center justify-between p-3.5 hover:bg-white/[0.02]">
                    <div>
                      <p className="text-sm font-medium text-zinc-200">{t.name}</p>
                      <p className="font-mono text-xs text-zinc-500">{t.prefix} · Created {t.created_at} · Last used: {t.last_used}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRevokeToken(t.id)}
                      className="rounded-md p-1.5 text-zinc-400 hover:bg-red-500/10 hover:text-red-400 transition-colors cursor-pointer"
                      title="Revoke Token"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 5. Notifications Tab */}
          {tab === "notifications" && (
            <div className="rounded-xl border border-white/10 bg-[var(--surface)] p-6 space-y-6">
              <div>
                <h2 className="text-base font-semibold text-zinc-100">Notification Preferences</h2>
                <p className="text-xs text-zinc-400">Choose when and how EnterpriseAI notifies you about agent events.</p>
              </div>

              <div className="space-y-4">
                <div className="flex items-start justify-between gap-4 py-2 border-b border-white/5">
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Execution Failure Alerts</p>
                    <p className="text-xs text-zinc-500">Receive immediate notifications when an automated workflow or agent encounters a fatal error.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={notifyOnFail}
                    onChange={(e) => setNotifyOnFail(e.target.checked)}
                    className="h-4 w-4 rounded border-zinc-700 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>

                <div className="flex items-start justify-between gap-4 py-2 border-b border-white/5">
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Pending Decision / Approval Alerts</p>
                    <p className="text-xs text-zinc-500">Alert me when an agent asks for human-in-the-loop authorization before sending an email or updating data.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={notifyOnApproval}
                    onChange={(e) => setNotifyOnApproval(e.target.checked)}
                    className="h-4 w-4 rounded border-zinc-700 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>

                <div className="flex items-start justify-between gap-4 py-2">
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Weekly Executive Digest</p>
                    <p className="text-xs text-zinc-500">Receive a weekly summary of token usage, most active agents, and cost savings.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={weeklyDigest}
                    onChange={(e) => setWeeklyDigest(e.target.checked)}
                    className="h-4 w-4 rounded border-zinc-700 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </ProtectedDashboard>
  );
}
