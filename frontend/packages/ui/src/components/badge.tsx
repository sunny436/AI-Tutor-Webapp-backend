import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "../utils";

/**
 * A small piece of state: a job status, a role, a count, a red flag.
 *
 * The app currently writes these by hand, and the recurring shape
 * `bg-emerald-500/10 text-emerald-700 dark:text-emerald-300` appears in six
 * files for three unrelated meanings — active navigation, an answered question,
 * and a success state. When one class string means three things, changing any
 * of them means auditing all of them.
 *
 * SEMANTIC COLOUR IS SEPARATE FROM THE BRAND, deliberately. `success` is not
 * `brand` even though both are green: "this is our colour" and "this worked" are
 * different statements, and a product where every good thing is brand-coloured
 * has no way left to say "good".
 */
const badgeVariants = cva(
  // `whitespace-nowrap` because these sit in table cells and flex rows where a
  // two-word status would otherwise wrap and change the row height.
  "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border px-2 py-0.5 text-xs font-semibold",
  {
    variants: {
      variant: {
        neutral: "border-border bg-surface-2 text-text-secondary",
        brand: "border-brand/20 bg-brand-soft text-brand",
        success: "border-success/20 bg-success-soft text-success",
        warning: "border-warning/25 bg-warning-soft text-warning",
        danger: "border-destructive/25 bg-destructive/10 text-destructive",
        info: "border-info/20 bg-info-soft text-info",
        // Provenance. The only variant using the warm accent, and it is
        // monospaced — a citation should read as data, not as a label someone
        // wrote. See the type roles in tailwind.config.ts.
        source:
          "border-accent-warm/25 bg-accent-warm-soft font-mono text-accent-warm",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
