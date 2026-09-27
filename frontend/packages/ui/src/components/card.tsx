import * as React from "react";

import { cn } from "../utils";

/**
 * The surface everything else sits on.
 *
 * WHY THIS EXISTS
 *
 * There was no Card component, so the app hand-built 17 of them. The raw combo
 * `rounded-lg border border-border bg-card` appears 9 times and
 * `rounded-2xl border border-border bg-card` another 8 — the same object, two
 * different corner radii, decided per file. Radius across the app had drifted to
 * five values (`rounded-lg` 35x, `2xl` 22x, `full` 21x, `xl` 18x, `md` 15x), and
 * the hover treatment came in two incompatible flavours (`-translate-y-1` with
 * `shadow-lg`, and `-translate-y-0.5` with `shadow-md`).
 *
 * One component, three deliberate variants — because a stat tile, a form panel
 * and a clickable list row are genuinely different objects and should not be
 * argued about again in each new file.
 */

type CardProps = React.HTMLAttributes<HTMLDivElement> & {
  /**
   * `flat`        a plain panel: forms, settings, prose.
   * `raised`      sits above the page. For summary tiles.
   * `interactive` the whole card is a link or button. Adds the lift, and only
   *               this variant does — a lift on something you cannot click is
   *               the interface lying about what is clickable.
   */
  variant?: "flat" | "raised" | "interactive";
};

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant = "flat", ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "rounded-2xl border border-border bg-card text-card-foreground elev-1",
        variant === "raised" && "elev-2",
        variant === "interactive" &&
          // `motion-safe:` rather than a bare hover transform: the global
          // reduced-motion rule kills the transition, but the transform itself
          // would still snap. This removes the movement entirely for anyone who
          // asked for less of it, and keeps the border/shadow feedback.
          "transition-[box-shadow,border-color,transform] duration-base hover:border-brand/40 hover:elev-2 motion-safe:hover:-translate-y-0.5 focus-within:border-brand/40",
        className,
      )}
      {...props}
    />
  ),
);
Card.displayName = "Card";

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col gap-1 p-5", className)}
    {...props}
  />
));
CardHeader.displayName = "CardHeader";

/**
 * `h3` by default, overridable with `as`. A card title is a heading, and a page
 * whose headings are all `div`s cannot be navigated by anyone using a screen
 * reader — but the right LEVEL depends on what encloses it, so it has to be a
 * choice rather than a hardcoded tag.
 */
const CardTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement> & { as?: "h2" | "h3" | "h4" }
>(({ className, as: Tag = "h3", ...props }, ref) => (
  <Tag
    ref={ref}
    className={cn("text-lg font-bold tracking-tight", className)}
    {...props}
  />
));
CardTitle.displayName = "CardTitle";

const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn("text-sm text-text-secondary", className)}
    {...props}
  />
));
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-5 pt-0", className)} {...props} />
));
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "flex items-center gap-2 border-t border-border p-5 py-3.5",
      className,
    )}
    {...props}
  />
));
CardFooter.displayName = "CardFooter";

export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
};
