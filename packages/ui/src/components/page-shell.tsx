import type * as React from "react";

import { cn } from "../utils";

/**
 * One page background, one measure, one heading rhythm.
 *
 * WHAT IT REPLACES
 *
 * The app currently has FOUR different page backgrounds, none of which is the
 * `--background` token:
 *
 *   dashboard / files / jobs   `bg-gradient-to-br from-emerald-50 via-white
 *                               to-teal-50 dark:from-zinc-950 dark:via-black
 *                               dark:to-emerald-950/30`   (byte-identical, x3)
 *   login                      the same, with `dark:to-emerald-950/40`
 *   consult                    `.backdrop-wash` — the one designed for this
 *   platform / settings        nothing at all
 *
 * So the same product renders on three different grounds depending on which
 * link you clicked, and `globals.css` says `body { @apply bg-background }`
 * while every one of those overrides it. The dark variant is worse than
 * inconsistent: `dark:via-black` reintroduces the pure black that the token
 * comment in globals.css explicitly rejects, because it crushes every shadow and
 * makes elevation impossible to express.
 *
 * `backdrop-wash` is the designed answer — two very low-opacity radial
 * gradients, sage from the top-left and saffron from the top-right, over the
 * real background token. It reads as light falling on paper rather than as a
 * gradient, and it already adapts to dark mode properly.
 *
 * `max-w-6xl` is a decision, not a default: these pages are read, and a stat row
 * stretched across a 27-inch monitor puts the first and last number a head-turn
 * apart.
 */
export function PageShell({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className="relative min-h-full w-full">
      {/* Fixed, not absolute: the wash should stay put while the page scrolls,
          or it repeats the gradient down a long document. */}
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div
        className={cn(
          "relative mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8",
          className,
        )}
        {...props}
      >
        {children}
      </div>
    </div>
  );
}

/**
 * The `h1` and its supporting line.
 *
 * A component rather than a convention because right now every page writes its
 * own — at four different sizes, three different weights, and with the icon
 * sometimes inside the heading and sometimes beside it. An icon inside an `h1`
 * also has to be `aria-hidden`, which is the kind of thing that is remembered
 * once and forgotten five times.
 */
export function PageHeader({
  title,
  description,
  icon: Icon,
  action,
  className,
}: {
  title: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string }>;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mb-6 flex flex-col gap-3 sm:mb-8 sm:flex-row sm:items-start sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="flex items-center gap-2.5 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          {Icon && (
            // Hidden from assistive tech: it decorates the title, and an
            // unlabelled glyph inside an h1 becomes part of the page's
            // accessible name for no benefit.
            <span
              aria-hidden
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"
            >
              <Icon className="h-[18px] w-[18px]" />
            </span>
          )}
          <span className="truncate">{title}</span>
        </h1>
        {description && (
          <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-text-secondary">
            {description}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
