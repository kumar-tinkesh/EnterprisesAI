"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Canvas on the left, a docked panel on the right (the playground). The
 * divider drags; the split is kept between 25% and 75% and remembered.
 */
export function SplitPane({
  open,
  left,
  right,
  storageKey = "builder.split",
}: {
  open: boolean;
  left: React.ReactNode;
  right: React.ReactNode;
  storageKey?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [share, setShare] = useState(50);
  const dragging = useRef(false);

  useEffect(() => {
    try {
      const saved = Number(window.localStorage.getItem(storageKey));
      if (saved >= 25 && saved <= 75) setShare(saved);
    } catch {
      /* storage unavailable: keep 50/50 */
    }
  }, [storageKey]);

  const onMove = useCallback(
    (e: PointerEvent) => {
      if (!dragging.current || !container.current) return;
      const box = container.current.getBoundingClientRect();
      const next = Math.min(75, Math.max(25, ((box.right - e.clientX) / box.width) * 100));
      setShare(next);
    },
    [],
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
      <div className="h-full min-w-0 flex-1">{left}</div>
      {open && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the playground"
            onPointerDown={() => {
              dragging.current = true;
              document.body.style.userSelect = "none";
            }}
            className="w-1.5 shrink-0 cursor-col-resize bg-zinc-200 transition-colors hover:bg-indigo-300"
          />
          <div className="h-full shrink-0 overflow-hidden border-l border-zinc-200 bg-white" style={{ width: `${share}%` }}>
            {right}
          </div>
        </>
      )}
    </div>
  );
}
