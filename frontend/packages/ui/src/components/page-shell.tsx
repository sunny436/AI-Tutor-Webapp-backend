import type * as React from "react";

import { cn } from "../utils";

/**
 * One page background, one measure, one heading rhythm.
 *
 * WHY IT EXISTS
 *
 * Pages that each choose their own background end up on several different
 * grounds depending on which link was clicked — and ad-hoc gradients drift into
 * pure black in dark mode, which the tokens in globals.css reject because it
 * crushes every shadow and makes elevation impossible to express.
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
const WIDTHS = {
  narrow: "max-w-3xl",
  default: "max-w-6xl",
  wide: "max-w-screen-xl",
} as const;

export function PageShell({
  width = "default",
  wash = true,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  /**
   * `max-w-6xl` was hardcoded, which is most of why eleven of fourteen pages
   * rolled their own container instead of adopting this: the dense admin
   * screens genuinely need more room, so they opted out entirely and lost the
   * wash and the padding rhythm with it.
   */
  width?: keyof typeof WIDTHS;
  /** Off when an ancestor already paints the wash, so it is not doubled. */
  wash?: boolean;
}) {
  return (
    <div className="relative min-h-full w-full">
      {/* Fixed, not absolute: the wash should stay put while the page scrolls,
          or it repeats the gradient down a long document. */}
      {wash && (
        <div
          aria-hidden
          className="backdrop-wash pointer-events-none fixed inset-0"
        />
      )}
      <div
        className={cn(
          "relative mx-auto w-full px-4 py-6 sm:px-6 sm:py-8",
          WIDTHS[width],
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
