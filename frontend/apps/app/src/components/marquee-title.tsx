"use client";

import { type CSSProperties, useLayoutEffect, useRef, useState } from "react";

/** Slide speed, the fade at the right edge, and the shortest cycle: slow enough to read. */
const SPEED_PX_PER_S = 30;
const FADE_PX = 24;
const MIN_CYCLE_MS = 8000;

/**
 * A chat's title in the sidebar. In full when it fits; when it does not, it fades out at the
 * right edge and every so often slides slowly to its end and back, waiting at each end. The
 * slide holds still while the row is hovered or focused and never runs with reduced motion, the
 * device's or the app's (globals.css). The text is always the whole title, so the link's
 * accessible name is the whole title however it is drawn.
 */
export function MarqueeTitle({ title }: { title: string }) {
  const box = useRef<HTMLSpanElement>(null);
  const track = useRef<HTMLSpanElement>(null);
  const [shift, setShift] = useState(0);

  useLayoutEffect(() => {
    const element = box.current;
    const text = track.current;
    if (!element || !text) return;
    const measure = () => {
      const overflow = text.offsetWidth - element.clientWidth;
      setShift(overflow > 1 ? overflow + FADE_PX : 0);
    };
    measure();
    // The row's width (sidebar, drawer, text size) and the title's (fonts arriving) both matter.
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    observer.observe(text);
    return () => observer.disconnect();
  }, [title]);

  const style = shift
    ? ({
        "--marquee-shift": `-${shift}px`,
        // A quarter of the cycle each way, a quarter waiting at each end.
        "--marquee-cycle": `${Math.round(Math.max(MIN_CYCLE_MS, (shift / SPEED_PX_PER_S) * 4000))}ms`,
      } as CSSProperties)
    : undefined;

  return (
    <span ref={box} className="marquee" data-overflowing={shift ? "" : undefined} style={style}>
      <span ref={track} className="marquee-track" dir="auto">
        {title}
      </span>
    </span>
  );
}
