"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Canvas on the left, a docked panel on the right (the playground). The
 * divider drags; the split is kept between ``min``% and ``max``% and remembered.
 *
 * With ``narrowShows`` set, screens narrower than ``lg`` show only that side,
 * full width (the host offers the switch); wider screens split as usual.
 */
export function SplitPane({
  open,
  left,
  right,
  storageKey = "builder.split",
  label = "Resize the playground",
  min = 25,
  max = 75,
  narrowShows,
}: {
  open: boolean;
  left: React.ReactNode;
  right: React.ReactNode;
  storageKey?: string;
  label?: string;
  min?: number;
  max?: number;
  narrowShows?: "left" | "right";
}) {
  const container = useRef<HTMLDivElement>(null);
  const [share, setShare] = useState(Math.min(max, Math.max(min, 50)));
  const dragging = useRef(false);

  useEffect(() => {
    try {
      const saved = Number(window.localStorage.getItem(storageKey));
      if (saved >= min && saved <= max) setShare(saved);
    } catch {
      /* storage unavailable: keep 50/50 */
    }
  }, [storageKey, min, max]);

  const onMove = useCallback(
    (e: PointerEvent) => {
      if (!dragging.current || !container.current) return;
      const box = container.current.getBoundingClientRect();
      const next = Math.min(max, Math.max(min, ((box.right - e.clientX) / box.width) * 100));
      setShare(next);
    },
    [min, max],
  );

  const stop = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    document.body.style.userSelect = "";
    try {
      window.localStorage.setItem(storageKey, String(Math.round(share)));
    } catch {
      /* ignore */
    }
  }, [share, storageKey]);

  useEffect(() => {
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stop);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", stop);
    };
  }, [onMove, stop]);

  return (
    <div ref={container} className="flex h-full w-full overflow-hidden">
      <div className={cn("h-full min-w-0 flex-1", open && narrowShows === "right" && "hidden lg:block")}>{left}</div>
      {open && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={label}
            onPointerDown={() => {
              dragging.current = true;
              document.body.style.userSelect = "none";
            }}
            className={cn("w-1.5 shrink-0 cursor-col-resize bg-zinc-200 transition-colors hover:bg-indigo-300", narrowShows && "hidden lg:block")}
          />
          {narrowShows ? (
            <div
              className={cn(
                "h-full shrink-0 overflow-hidden border-zinc-200 bg-white lg:w-[var(--split-share)] lg:border-l",
                narrowShows === "left" ? "hidden lg:block" : "w-full",
              )}
              style={{ "--split-share": `${share}%` } as React.CSSProperties}
            >
              {right}
            </div>
          ) : (
            <div className="h-full shrink-0 overflow-hidden border-l border-zinc-200 bg-white" style={{ width: `${share}%` }}>
              {right}
            </div>
          )}
        </>
      )}
    </div>
  );
}
