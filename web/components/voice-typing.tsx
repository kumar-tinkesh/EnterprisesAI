"use client";

/**
 * Speak to type, on every text field in the app.
 *
 * Mounted once (in Providers). When a text input or textarea gets focus, a
 * mic appears inside its right edge. Tap it and speak; the words go in where
 * the cursor was. No field has to opt in.
 *
 * - Chrome / Edge / Safari: the browser's own speech recognition, words show
 *   up while you talk.
 * - Other browsers (Firefox), or when that fails: the clip is recorded and
 *   sent to POST /builder/assist/transcribe (Whisper), signed-in users only.
 *
 * Left out: passwords, email / number / URL / phone fields, one-time codes,
 * monospace (keys, code) and very narrow boxes, read-only and disabled ones,
 * and anything inside or marked with data-voice="off".
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";

import { builderApi } from "@/lib/builder/api";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

type Field = HTMLInputElement | HTMLTextAreaElement;
type Phase = "idle" | "listening" | "recording" | "writing";

const LANGS = [
  { code: "en-IN", short: "EN", name: "English" },
  { code: "hi-IN", short: "हि", name: "हिन्दी" },
] as const;
const LANG_KEY = "voice-typing-lang";
const BTN = 28;
const MAX_RECORD_MS = 120_000;
const NO_AUTOCOMPLETE = /^(email|username|current-password|new-password|one-time-code|tel|url|cc-|postal-code)/;
const NO_INPUTMODE = new Set(["numeric", "decimal", "email", "tel", "url", "none"]);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Recognition = any;

function speechRecognition(): (new () => Recognition) | null {
  if (typeof window === "undefined") return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

function canRecord(): boolean {
  return typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia;
}

function eligible(el: Element | null): el is Field {
  if (!el) return false;
  let field: Field;
  if (el instanceof HTMLTextAreaElement) field = el;
  else if (el instanceof HTMLInputElement) {
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (type !== "text" && type !== "search") return false;
    field = el;
  } else return false;
  if (field.readOnly || field.disabled) return false;
  if (field.closest('[data-voice="off"]')) return false;
  if (NO_AUTOCOMPLETE.test((field.getAttribute("autocomplete") || "").toLowerCase())) return false;
  if (NO_INPUTMODE.has((field.getAttribute("inputmode") || "").toLowerCase())) return false;
  if (field.classList.contains("font-mono")) return false;
  return field.getBoundingClientRect().width >= 140;
}

/** Put text into a React-managed field so its onChange / react-hook-form sees it. */
function setFieldValue(el: Field, value: string, caret: number) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  try {
    el.setSelectionRange(caret, caret);
  } catch {
    /* some inputs don't take a selection */
  }
}

function readLang(): string {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved && LANGS.some((l) => l.code === saved)) return saved;
  } catch {
    /* storage blocked */
  }
  return typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("hi") ? "hi-IN" : "en-IN";
}

export function VoiceTyping() {
  const [field, setField] = useState<Field | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [lang, setLangState] = useState("en-IN");
  const langRef = useRef("en-IN");
  const setLang = (l: string) => {
    langRef.current = l;
    setLangState(l);
  };
  const [note, setNote] = useState<string | null>(null);
  const [supported, setSupported] = useState({ speech: false, record: false });
  const token = useAuthStore((s) => s.accessToken);

  const fieldRef = useRef<Field | null>(null);
  const pressingMic = useRef(false);
  const recognition = useRef<Recognition>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stopTimer = useRef<number | null>(null);
  // Where the spoken words go: the text before / after the cursor when the mic started.
  const insertAt = useRef<{ before: string; after: string; done: string }>({ before: "", after: "", done: "" });
  const savedPadding = useRef<string>("");

  useEffect(() => {
    setSupported({ speech: !!speechRecognition(), record: canRecord() });
    setLang(readLang());
  }, []);

  const canServer = supported.record && !!token;
  const usable = supported.speech || canServer;

  // ── follow focus ──────────────────────────────────────────────────────────
  const place = useCallback(() => {
    const el = fieldRef.current;
    if (!el || !el.isConnected) return setPos(null);
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.bottom < 0 || r.top > window.innerHeight) return setPos(null);
    const top = el instanceof HTMLTextAreaElement && r.height > 48 ? r.bottom - BTN - 6 : r.top + (r.height - BTN) / 2;
    setPos({ top, left: r.right - BTN - 4 });
  }, []);

  const detach = useCallback(() => {
    const el = fieldRef.current;
    if (el) el.style.paddingRight = savedPadding.current;
    fieldRef.current = null;
    setField(null);
    setPos(null);
    setNote(null);
  }, []);

  useEffect(() => {
    if (!usable) return;
    function onFocusIn(e: FocusEvent) {
      const el = e.target as Element;
      if (el === fieldRef.current || pressingMic.current || el.closest?.("[data-voice-ui]")) return;
      if (fieldRef.current) detach();
      if (!eligible(el)) return;
      fieldRef.current = el;
      savedPadding.current = el.style.paddingRight;
      const current = parseFloat(getComputedStyle(el).paddingRight) || 0;
      if (current < BTN + 8) el.style.paddingRight = `${BTN + 8}px`;
      setField(el);
      place();
    }
    function onFocusOut(e: FocusEvent) {
      if (e.target !== fieldRef.current) return;
      // Pressing the mic (or the language pill) moves focus off the field; keep it.
      window.setTimeout(() => {
        if (pressingMic.current) return;
        if (document.activeElement === fieldRef.current) return;
        stopAll();
        detach();
      }, 120);
    }
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usable, detach, place]);

  useEffect(() => {
    if (!field) return;
    const onMove = () => place();
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    const ro = new ResizeObserver(onMove);
    ro.observe(field);
    return () => {
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
      ro.disconnect();
    };
  }, [field, place]);

  // ── writing words into the field ──────────────────────────────────────────
  function beginInsert() {
    const el = fieldRef.current!;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    insertAt.current = { before: el.value.slice(0, start), after: el.value.slice(end), done: "" };
  }

  function write(spoken: string) {
    const el = fieldRef.current;
    if (!el) return;
    const { before, after } = insertAt.current;
    const text = spoken.trim();
    if (!text) return;
    const lead = before && !/\s$/.test(before) ? " " : "";
    const tail = after && !/^\s/.test(after) ? " " : "";
    let value = before + lead + text + tail + after;
    if (el.maxLength > 0) value = value.slice(0, el.maxLength);
    setFieldValue(el, value, (before + lead + text).length);
  }

  // ── browser speech recognition ────────────────────────────────────────────
  function startSpeech() {
    const SR = speechRecognition()!;
    const rec = new SR();
    rec.lang = langRef.current;
    rec.continuous = true;
    rec.interimResults = true;
    let fellBack = false;
    rec.onresult = (e: Recognition) => {
      let finals = "";
      let interim = "";
      for (let i = 0; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finals += t;
        else interim += t;
      }
      insertAt.current.done = finals;
      write(`${finals} ${interim}`);
    };
    rec.onerror = (e: Recognition) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") setNote("Mic is blocked. Allow it in the browser's site settings.");
      else if (e.error === "network" && canServer) {
        // e.g. Brave: has the API but no speech service — record instead.
        fellBack = true;
        setSupported((s) => ({ ...s, speech: false }));
      } else if (e.error === "no-speech") setNote("Didn't hear anything. Tap the mic and try again.");
      else if (e.error !== "aborted") setNote("Voice typing stopped. Try again.");
    };
    rec.onend = () => {
      recognition.current = null;
      setPhase("idle");
      if (fellBack) void startRecording();
    };
    recognition.current = rec;
    beginInsert();
    setNote(null);
    setPhase("listening");
    try {
      rec.start();
    } catch {
      setPhase("idle");
    }
  }

  // ── record and send to the server ─────────────────────────────────────────
  async function startRecording() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setNote("Mic is blocked. Allow it in the browser's site settings.");
      return;
    }
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported?.(t));
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      if (stopTimer.current) window.clearTimeout(stopTimer.current);
      recorder.current = null;
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      const t = useAuthStore.getState().accessToken;
      if (!blob.size || !t) return setPhase("idle");
      setPhase("writing");
      try {
        const { text } = await builderApi.transcribe(t, blob, langRef.current);
        if (text) write(text);
        else setNote("Didn't catch any words. Try again.");
      } catch {
        setNote("Couldn't turn that into text. Try again.");
      } finally {
        setPhase("idle");
      }
    };
    recorder.current = rec;
    beginInsert();
    setNote(null);
    setPhase("recording");
    rec.start();
    stopTimer.current = window.setTimeout(() => rec.state !== "inactive" && rec.stop(), MAX_RECORD_MS);
  }

  function stopAll() {
    recognition.current?.stop();
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
  }

  function toggle() {
    if (phase === "listening" || phase === "recording") return stopAll();
    if (phase === "writing") return;
    if (supported.speech) startSpeech();
    else if (canServer) void startRecording();
  }

  function switchLang() {
    const next = LANGS[(LANGS.findIndex((l) => l.code === lang) + 1) % LANGS.length].code;
    setLang(next);
    try {
      localStorage.setItem(LANG_KEY, next);
    } catch {
      /* storage blocked */
    }
    // Listening already: carry on in the new language after what was said.
    if (recognition.current) {
      recognition.current.onend = () => {
        recognition.current = null;
        startSpeech();
      };
      recognition.current.stop();
    }
  }

  // Leaving the page mid-sentence: let go of the mic.
  useEffect(() => () => stopAll(), []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!field || !pos || !usable) return null;

  const active = phase === "listening" || phase === "recording";
  const current = LANGS.find((l) => l.code === lang) ?? LANGS[0];
  // Keep focus on the field: note the press, then hand focus back after.
  const press = {
    onPointerDown: () => {
      pressingMic.current = true;
    },
    onPointerUp: () => {
      window.setTimeout(() => {
        pressingMic.current = false;
        fieldRef.current?.focus({ preventScroll: true });
      }, 0);
    },
    onPointerCancel: () => {
      pressingMic.current = false;
    },
  };
  const above = pos.top > 48;

  return (
    <>
      <button
        type="button"
        tabIndex={-1}
        data-voice-ui
        aria-label={active ? "Stop voice typing" : `Speak to type (${current.name})`}
        title={active ? "Stop" : `Speak to type · ${current.name}`}
        onClick={toggle}
        {...press}
        style={{ top: pos.top, left: pos.left, width: BTN, height: BTN }}
        className={cn(
          "fixed z-[200] flex items-center justify-center rounded-md transition-colors cursor-pointer",
          active
            ? "bg-[var(--danger-wash)] text-[var(--danger)]"
            : "text-[var(--text-subtle)] hover:bg-[var(--hover)] hover:text-[var(--text)]",
        )}
      >
        {phase === "writing" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : active ? (
          <Square className="h-3 w-3 fill-current" />
        ) : (
          <Mic className="h-4 w-4" />
        )}
        {active && <span className="pointer-events-none absolute inset-0 animate-ping rounded-md bg-[var(--danger-wash)]" />}
      </button>

      {(active || phase === "writing" || note) && (
        <div
          role="status"
          aria-live="polite"
          data-voice-ui
          style={{ top: above ? pos.top - 36 : pos.top + BTN + 6, left: Math.max(8, pos.left + BTN - 260), width: 260 }}
          className="pointer-events-none fixed z-[200] flex justify-end"
        >
          <span className="pointer-events-auto flex max-w-full items-center gap-2 rounded-md border border-[var(--border-strong)] bg-[var(--surface-raised)] px-2 py-1 text-xs text-[var(--text-muted)] shadow-lg">
            {note ?? (phase === "writing" ? "Writing it down…" : "Listening…")}
            {active && (
              <button
                type="button"
                tabIndex={-1}
                onClick={switchLang}
                {...press}
                title="Change language"
                className="rounded border border-[var(--border-strong)] px-1.5 text-[var(--text)] hover:bg-[var(--hover)] cursor-pointer"
              >
                {current.short}
              </button>
            )}
          </span>
        </div>
      )}
    </>
  );
}
