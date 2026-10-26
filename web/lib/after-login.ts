"use client";

/**
 * Where to go once signed in: back to the page that sent them to /auth
 * (/auth?next=/r/abc — a share link), else their dashboard. Kept in
 * sessionStorage so it survives the Google sign-in round trip.
 */

import { dashboardPathForRole, type Role } from "@/lib/validations";

const KEY = "auth.next";

/** Only paths inside this app ("/r/abc"), never "//evil.com" or a full URL. */
function safe(path: string | null): path is string {
  return !!path && path.startsWith("/") && !path.startsWith("//") && !path.startsWith("/\\");
}

export function rememberNext(path: string | null) {
  try {
    if (safe(path)) window.sessionStorage.setItem(KEY, path);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    /* no storage: they land on their dashboard */
  }
}

export function afterLoginPath(role: Role): string {
  try {
    const next = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    if (safe(next)) return next;
  } catch {
    /* fall through */
  }
  return dashboardPathForRole(role);
}
