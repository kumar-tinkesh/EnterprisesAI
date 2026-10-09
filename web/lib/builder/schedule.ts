/**
 * The schedule picker's presets <-> a 5-field cron expression.
 * Anything the presets can't express stays "custom" (the raw cron is kept).
 */

export type Repeat = "daily" | "weekdays" | "weekly" | "monthly" | "hours" | "custom";

export interface SchedulePreset {
  repeat: Repeat;
  /** "HH:MM", 24h. */
  time: string;
  /** 0 = Sunday … 6 = Saturday (weekly). */
  weekday: number;
  /** 1-28 (monthly). */
  day: number;
  /** Every N hours (hours). */
  every: number;
  /** The expression itself (custom). */
  cron: string;
}

export const DEFAULT_CRON = "0 9 * * 1-5";

export const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export const REPEAT_LABELS: Record<Repeat, string> = {
  daily: "Every day",
  weekdays: "Weekdays (Mon–Fri)",
  weekly: "Every week",
  monthly: "Every month",
  hours: "Every few hours",
  custom: "Custom (cron)",
};

const num = (v: string) => /^\d+$/.test(v);
const pad = (n: number) => String(n).padStart(2, "0");

export function parseCron(cron: string): SchedulePreset {
  const base: SchedulePreset = { repeat: "custom", time: "09:00", weekday: 1, day: 1, every: 2, cron };
  const parts = (cron || "").trim().split(/\s+/);
  if (parts.length !== 5) return base;
  const [m, h, dom, mon, dow] = parts;
  if (mon !== "*" || !num(m)) return base;
  if (h.startsWith("*/") && num(h.slice(2)) && dom === "*" && dow === "*" && m === "0") {
    return { ...base, repeat: "hours", every: Number(h.slice(2)) };
  }
  if (!num(h)) return base;
  const time = `${pad(Number(h))}:${pad(Number(m))}`;
  if (dom === "*" && dow === "*") return { ...base, repeat: "daily", time };
  if (dom === "*" && dow === "1-5") return { ...base, repeat: "weekdays", time };
  if (dom === "*" && num(dow) && Number(dow) <= 6) return { ...base, repeat: "weekly", time, weekday: Number(dow) };
  if (num(dom) && Number(dom) >= 1 && Number(dom) <= 28 && dow === "*") return { ...base, repeat: "monthly", time, day: Number(dom) };
  return base;
}

export function buildCron(p: SchedulePreset): string {
  if (p.repeat === "custom") return p.cron.trim();
  if (p.repeat === "hours") return `0 */${Math.min(23, Math.max(1, Math.round(p.every) || 1))} * * *`;
  const [hh, mm] = (p.time || "09:00").split(":").map((x) => Number(x) || 0);
  const at = `${Math.min(59, mm)} ${Math.min(23, hh)}`;
  if (p.repeat === "daily") return `${at} * * *`;
  if (p.repeat === "weekdays") return `${at} * * 1-5`;
  if (p.repeat === "weekly") return `${at} * * ${p.weekday}`;
  return `${at} ${Math.min(28, Math.max(1, p.day))} * *`;
}

/** A canvas-sized summary of a trigger's schedule ("Weekdays 09:00 · Asia/Kolkata"). */
export function describeSchedule(s: { cron?: string; timezone?: string; enabled?: boolean } | null | undefined): string {
  if (!s?.cron) return "Not scheduled yet";
  if (s.enabled === false) return "Paused";
  const p = parseCron(s.cron);
  const when =
    p.repeat === "daily" ? `Daily ${p.time}`
    : p.repeat === "weekdays" ? `Weekdays ${p.time}`
    : p.repeat === "weekly" ? `${WEEKDAYS[p.weekday]}s ${p.time}`
    : p.repeat === "monthly" ? `Monthly, day ${p.day}, ${p.time}`
    : p.repeat === "hours" ? `Every ${p.every}h`
    : `Cron ${s.cron}`;
  return `${when} · ${s.timezone || "UTC"}`;
}

/** "Thu, 9 Oct, 9:00 AM" in the viewer's locale, shown in the schedule's own timezone. */
export function formatRunTime(iso: string, timezone?: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
      ...(timezone ? { timeZone: timezone } : {}),
    });
  } catch {
    return new Date(iso).toLocaleString();
  }
}

/** A short list for the timezone field's suggestions (any IANA name is accepted). */
export const COMMON_TIMEZONES = [
  "UTC", "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Europe/London", "Europe/Berlin",
  "America/New_York", "America/Chicago", "America/Los_Angeles", "Australia/Sydney",
];
