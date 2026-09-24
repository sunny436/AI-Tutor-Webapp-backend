import * as React from "react";

import { cn } from "../utils";

/**
 * Tabular data — jobs, members, audit entries, events.
 *
 * The app builds these by hand today, and every one of them has the same two
 * problems:
 *
 * 1. NO HORIZONTAL CONTAINMENT. A table with five columns and a timestamp does
 *    not fit 375px, so the widest cell pushes the page itself sideways and the
 *    whole layout scrolls — including the header and the sidebar. `<Table>`
 *    wraps itself in an `overflow-x-auto` container so the table scrolls inside
 *    its own bounds and the page never does. `tabindex=0` on that container is
 *    required, not decorative: a scrollable region that cannot be focused cannot
 *    be scrolled by keyboard at all.
 *
 * 2. NO HEADER SEMANTICS. Hand-built rows use `<div>`s or bare `<td>`s, so a
 *    screen reader cannot say which column a cell belongs to. `<th scope="col">`
 *    is what makes "Status: failed" audible instead of just "failed".
 *
 * `tabular-nums` on cells because these are lists of counts and dates read down
 * a column, and proportional digits make them ragged.
 */

const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement> & { label?: string }
>(({ className, label, ...props }, ref) => (
  <div
    // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard-focusable to be scrollable
    tabIndex={0}
    role="region"
    aria-label={label}
    className="focus-ring w-full overflow-x-auto rounded-xl border border-border"
  >
    <table
      ref={ref}
      className={cn("w-full caption-bottom text-sm", className)}
      {...props}
    />
  </div>
));
Table.displayName = "Table";

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("bg-surface-2/60", className)} {...props} />
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...props}
  />
));
TableBody.displayName = "TableBody";

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b border-border transition-colors hover:bg-surface-2/50",
      className,
    )}
    {...props}
  />
));
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, scope = "col", ...props }, ref) => (
  <th
    ref={ref}
    scope={scope}
    className={cn(
      "h-10 whitespace-nowrap px-4 text-left align-middle text-xs font-semibold uppercase tracking-wide text-text-secondary",
      className,
    )}
    {...props}
  />
));
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn("px-4 py-3 align-middle tabular-nums", className)}
    {...props}
  />
));
TableCell.displayName = "TableCell";

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-3 text-xs text-text-secondary", className)}
    {...props}
  />
));
TableCaption.displayName = "TableCaption";

export {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableCaption,
};
