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
 * All this measures is how far the title overflows its row. No timers, no animation frames: the
 * movement is a CSS transform, and the observer is disconnected with the row.
 */
export function MarqueeTitle({ title }: { title: string }) {
  const box = useRef<HTMLSpanElement>(null);
  const [shift, setShift] = useState(0);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    let mounted = true;
    const measure = () => {
      const overflow = element.scrollWidth - element.clientWidth;
      setShift(overflow > 1 ? overflow + FADE_PX : 0);
    };
    measure();
    // The row's width changes with the sidebar, the drawer and the text size...
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    // ...and the title's own width once the web font has arrived.
    void document.fonts?.ready.then(() => mounted && measure());
    return () => {
      mounted = false;
      observer.disconnect();
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
