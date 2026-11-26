"use client";

import { useEffect, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Side effect: API calls skip ngrok's browser warning page when the app runs behind ngrok.
import "@/lib/ngrok";
import { VoiceTyping } from "@/components/voice-typing";

export const APPEARANCE_KEY = "enterpriseai.appearance";
export type ThemeTone = "calm_dark" | "midnight" | "zinc";
export type AppearancePrefs = {
  theme: ThemeTone;
  compact: boolean;
  animations: boolean;
};

export const DEFAULT_APPEARANCE: AppearancePrefs = {
  theme: "calm_dark",
  compact: false,
  animations: true,
};

export function applyAppearance(prefs: AppearancePrefs) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (prefs.theme && prefs.theme !== "calm_dark") root.setAttribute("data-theme", prefs.theme);
  else root.removeAttribute("data-theme");
  if (prefs.compact) root.setAttribute("data-density", "compact");
  else root.removeAttribute("data-density");
  if (!prefs.animations) root.setAttribute("data-reduce-motion", "true");
  else root.removeAttribute("data-reduce-motion");
}

export function loadAppearance(): AppearancePrefs {
  try {
    const raw = window.localStorage.getItem(APPEARANCE_KEY);
    if (!raw) return DEFAULT_APPEARANCE;
    const parsed = JSON.parse(raw) as Partial<AppearancePrefs>;
    return {
      theme: parsed.theme === "midnight" || parsed.theme === "zinc" ? parsed.theme : "calm_dark",
      compact: Boolean(parsed.compact),
      animations: parsed.animations !== false,
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );

  useEffect(() => {
    applyAppearance(loadAppearance());
  }, []);

  return (
    <QueryClientProvider client={client}>
      {children}
      <VoiceTyping />
    </QueryClientProvider>
  );
}
