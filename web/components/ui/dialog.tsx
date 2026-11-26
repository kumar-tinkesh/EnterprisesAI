"use client";

import { useEffect } from "react";
import { X } from "lucide-react";

/** A centred popup that fits any screen: scrolls inside itself, closes on Esc or a click outside. */
export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <button type="button" aria-label="Close" className="animate-fade-in absolute inset-0 bg-black/65 backdrop-blur-sm" onClick={onClose} />
      <div className="animate-scale-in relative max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-xl border border-white/10 bg-[var(--surface-raised)] p-5 shadow-2xl ring-1 ring-white/5 sm:p-6">
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer">
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
