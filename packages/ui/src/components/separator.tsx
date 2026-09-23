import * as React from "react";

import { cn } from "../utils";

/**
 * A rule between things.
 *
 * Hand-written rather than `@radix-ui/react-separator`, which is not a
 * dependency here. Radix's version is a `div` with `role="separator"` and an
 * orientation attribute — about fifteen lines — so pulling in a package to get
 * it would add install weight for no behaviour we do not have.
 *
 * `decorative` matters and is the reason this is a component at all. A rule that
 * merely groups things visually must be `aria-hidden`, or a screen reader
 * announces "separator" between every section and turns a settings page into a
 * list of interruptions. A rule that carries real meaning — the divider between
 * a menu's destructive action and everything above it — must NOT be hidden,
 * because that grouping is the only thing warning the user. Default decorative,
 * since that is the common case; opt out where the line means something.
 */
const Separator = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    orientation?: "horizontal" | "vertical";
    decorative?: boolean;
  }
>(
  (
    { className, orientation = "horizontal", decorative = true, ...props },
    ref,
  ) => (
    <div
      ref={ref}
      {...(decorative
        ? { "aria-hidden": true, role: "none" }
        : { role: "separator", "aria-orientation": orientation })}
      className={cn(
        "shrink-0 bg-border",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
      {...props}
    />
  ),
);
Separator.displayName = "Separator";

export { Separator };
