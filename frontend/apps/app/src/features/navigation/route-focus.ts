"use client";

import { useEffect } from "react";

/**
 * Where keyboard and screen-reader focus goes when a whole view is replaced by a client-side
 * navigation (the app and the Settings workspace swap each other): the control that was used
 * is gone, so focus would fall back to <body> and the next Tab would start from the top.
 *
 * Only then, and never on a fresh page load (the browser's own starting point is right there).
 * A view that already placed focus itself (the chat's message box) is left alone.
 */

let viewMounted = false;

/** True when a view mounts after another one in this page load: a client-side arrival. */
export function arrivingFromAnotherView(): boolean {
  const arriving = viewMounted;
  viewMounted = true;
  return arriving;
}

const CONTROL = "a[href], button, input, select, textarea, summary, [contenteditable='true']";

/**
 * Focus is nowhere useful: on <body>, on something removed, on an element nobody made
 * focusable, or on <main> itself. Next focuses a new page's first element after navigating,
 * and Chrome lets a scrolling <div> take it; WebKit, on a tap, focuses the nearest focusable
 * ancestor of the link instead of the link, which is <main> (focusable only as the skip link's
 * target). None of these tells anyone where they are.
 */
export function focusLost(): boolean {
  const active = document.activeElement;
  if (!active || active === document.body || !document.contains(active)) return true;
  if (active.matches("main")) return true;
  return !active.hasAttribute("tabindex") && !active.matches(CONTROL);
}

export function focusIfLost(target: HTMLElement | null | undefined): void {
  if (focusLost()) target?.focus({ preventScroll: true });
}

export function useFocusOnArrival(target: () => HTMLElement | null | undefined): void {
  // On arrival only: `target` is read when the frame runs.
  useEffect(() => {
    if (!arrivingFromAnotherView()) return;
    // After the view's own effects (a child may focus itself) and the first paint.
    const frame = requestAnimationFrame(() => focusIfLost(target()));
    return () => cancelAnimationFrame(frame);
  }, []);
}
