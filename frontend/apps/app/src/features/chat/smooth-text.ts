"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A streaming reply shown at an even pace instead of in the bursts the network delivers.
 *
 * No invented delay: the text shown is always text that has arrived, and each tick shows a third
 * of what is waiting (at least a few characters, ending on a word when one is near), so it is
 * never more than a few ticks behind and catches up at once after a burst. Ticks are as far apart
 * as the chat store's own updates (~50 ms), so revealing costs no extra renders, and they stop
 * whenever nothing is waiting. The moment the reply stops streaming, all of it shows.
 */
export const TICK_MS = 50;

/** The next length of `text` to show after `shown` characters. */
export function nextReveal(text: string, shown: number): number {
  const received = text.length;
  if (shown >= received) return received;
  let end = Math.min(received, shown + Math.max(3, Math.ceil((received - shown) / 3)));
  if (end < received) {
    const space = text.slice(end, end + 16).search(/\s/);
    if (space !== -1) end += space;
  }
  return end;
}

export function useSmoothText(text: string, live: boolean): string {
  const latest = useRef(text);
  latest.current = text;
  // A reply already on screen when this mounts (coming back to a streaming chat) is not replayed.
  const [shown, setShown] = useState(() => text.length);
  const behind = live && shown < text.length;

  useEffect(() => {
    if (!behind) return;
    const timer = setInterval(() => setShown((current) => nextReveal(latest.current, current)), TICK_MS);
    return () => clearInterval(timer);
  }, [behind]);

  return live ? text.slice(0, shown) : text;
}
