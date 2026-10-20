"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Watch answers being written (streaming) or get them whole — this viewer's
 * choice, on by default, remembered in this browser. One setting for the
 * chat, the playground, the canvas and share links.
 */
const KEY = "builder.stream";
const EVENT = "builder-stream-pref";

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

export function useStreamPref(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(true);
  useEffect(() => {
    setOn(read());
    // Every toggle on the page follows a change made in any one of them.
    const sync = () => setOn(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const set = useCallback((next: boolean) => {
    setOn(next);
    try {
      window.localStorage.setItem(KEY, next ? "on" : "off");
    } catch {
      /* this page only */
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [on, set];
}
