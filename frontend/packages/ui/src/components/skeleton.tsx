import type * as React from "react";

import { cn } from "../utils";

/**
 * A placeholder with the shape of the thing that is coming.
 *
 * Two reasons this is a component rather than a class.
 *
 * 1. There is no `loading.tsx` anywhere in the app, and the three pages that do
 *    show a loading state each invented their own — `files` uses pulsing cards,
 *    `jobs` and `platform` render the word "Loading…". Same wait, three answers.
 *
 * 2. ACCESSIBILITY. A pulsing grey box says nothing out loud, so a screen-reader
 *    user hears silence and cannot tell "loading" from "empty". `aria-hidden`
 *    keeps the decoration silent and `<SkeletonGroup>` speaks once for the whole
 *    region — one "Loading" announcement, not one per box.
 *
 * `animate-soft-pulse` rather than Tailwind's `animate-pulse`: the built-in
 * fades to 0.5 opacity on a 2s cubic curve, which reads as a heartbeat next to
 * text. Ours is a slower, shallower breath, and it is one of the two animations
 * the reduced-motion rule has always disabled.
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("animate-soft-pulse rounded-lg bg-surface-2", className)}
      {...props}
    />
  );
}

/**
 * Wraps a set of skeletons and announces the wait exactly once.
 *
 * `aria-busy` is what assistive tech reads to mean "this region is still
 * arriving"; without it a skeleton screen is indistinguishable from a broken one.
 */
function SkeletonGroup({
  label = "Loading",
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { label?: string }) {
  return (
    <div role="status" aria-busy="true" className={cn(className)} {...props}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

export { Skeleton, SkeletonGroup };
