"use client";

import { type CSSProperties, useLayoutEffect, useRef, useState } from "react";

/** Slide speed, the fade kept clear at the right edge, and the shortest cycle: slow enough to read. */
const SPEED_PX_PER_S = 30;
const FADE_PX = 20;
const MIN_CYCLE_MS = 8000;

/**
 * A chat's title in the sidebar. At rest it never moves: one line, ending in an ellipsis when it
 * does not fit, with a sharp start. Only while its row is hovered, or holds keyboard focus, does
 * a title that overflows slide slowly to its end and back (globals.css, `.marquee`); reduced
 * motion, the device's or the app's, never moves it. The text is always the whole title, so the
 * link's accessible name is the whole title however it is drawn.
 *
 * All this measures is how far the title overflows its row, and only when its row is hovered or
 * takes focus, the only times it can move: measuring every title as the list mounts or resizes
 * forced a reflow per title (0.5 s opening the phone's drawer, CPU 4x, 2026-10-23), and a touch
 * screen never needs it. No timers, no animation frames: the movement is a CSS transform.
 */
export function MarqueeTitle({ title }: { title: string }) {
  const box = useRef<HTMLSpanElement>(null);
  const [shift, setShift] = useState(0);

  useLayoutEffect(() => {
    const element = box.current;
    const row = element?.closest("li") ?? element;
    if (!element || !row) return;
    setShift(0); // a renamed chat is measured again on its next hover or focus
    const measure = () => {
      const overflow = element.scrollWidth - element.clientWidth;
      setShift(overflow > 1 ? overflow + FADE_PX : 0);
    };
    row.addEventListener("pointerenter", measure);
    row.addEventListener("focusin", measure);
    return () => {
      row.removeEventListener("pointerenter", measure);
      row.removeEventListener("focusin", measure);
    };
  }, [title]);

  const style = shift
    ? ({
        "--marquee-shift": `-${shift}px`,
        // Three fifths of the cycle moving (there and back), the rest resting at either end.
        "--marquee-cycle": `${Math.round(Math.max(MIN_CYCLE_MS, (shift / SPEED_PX_PER_S) * 3200))}ms`,
      } as CSSProperties)
    : undefined;

  return (
    <span ref={box} className="marquee" data-overflowing={shift ? "" : undefined} style={style}>
      <span className="marquee-track" dir="auto">
        {title}
      </span>
    </span>
  );
}
