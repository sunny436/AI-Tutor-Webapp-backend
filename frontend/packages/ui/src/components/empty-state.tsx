import type { LucideIcon } from "lucide-react";
import type * as React from "react";

import { cn } from "../utils";

/**
 * What a screen says when it has nothing to show.
 *
 * The brief asks every empty state to answer three questions, and the shape
 * below enforces them rather than trusting each page to remember:
 *
 *   title        what is empty
 *   description  why that matters / what would fill it
 *   action       the one thing to do next
 *
 * `action` is deliberately not optional-by-convention. An empty state without a
 * way forward is a dead end: "No chats yet." is true, unhelpful, and leaves the
 * reader to work out what to do. If a screen genuinely has no next step, pass `null`
 * explicitly so it is a decision rather than an omission.
 *
 * ErrorState lives here too because it is the same object with a different
 * temperature: something is missing, here is why, here is what to do.
 */

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action: React.ReactNode | null;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      {Icon && (
        <span className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-surface-2 text-text-secondary">
          <Icon aria-hidden className="h-5 w-5" />
        </span>
      )}
      <p className="font-display text-base font-semibold text-foreground">
        {title}
      </p>
      {description && (
        <p className="mt-1 max-w-sm text-sm leading-relaxed text-text-secondary">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/**
 * A failure the reader can act on.
 *
 * `role="alert"` so it is announced when it replaces content mid-session — an
 * error that appears silently after a retry is an error the user does not know
 * happened. Never renders a stack trace or a status code: those belong in the
 * log, and the reader needs to know what to do, not what broke.
 */
export function ErrorState({
  icon: Icon,
  title = "Something went wrong",
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title?: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-destructive/25 bg-destructive/5 px-6 py-10 text-center",
        className,
      )}
    >
      {Icon && (
        <span className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-destructive/10 text-destructive">
          <Icon aria-hidden className="h-5 w-5" />
        </span>
      )}
      <p className="font-display text-base font-semibold text-foreground">
        {title}
      </p>
      {description && (
        <p className="mt-1 max-w-sm text-sm leading-relaxed text-text-secondary">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
