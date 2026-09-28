"use client";

import * as SwitchPrimitives from "@radix-ui/react-switch";
import * as React from "react";

import { cn } from "../utils";

/**
 * `data-[state=checked]:bg-primary` was a real dark-mode bug, not a nit:
 * `--primary` is this codebase's near-black/near-WHITE text colour, so an "on"
 * switch in dark mode rendered as a pale slab that read as disabled. "On" is
 * `--brand` everywhere else in the product, and now here too.
 *
 * Geometry went h-5/w-9 -> h-6/w-11. With `border-2` that is a 40px content
 * box around a 20px thumb, so the 20px travel that `translate-x-5` describes
 * is still exact. The unchecked track also moves off `--input`, whose role is
 * *field border*, onto `--surface-2` with a real border: secondary text at 75%,
 * 3.3:1 on a card in light and 4.6:1 in dark, so an "off" switch is still clearly
 * a switch (WCAG 1.4.11 asks 3:1 of a control's boundary; the page's hairline
 * border, at 1.25:1, did not qualify).
 */
const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      "peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 transition-colors focus-ring disabled:cursor-not-allowed disabled:opacity-50",
      "data-[state=checked]:border-brand data-[state=checked]:bg-brand",
      "data-[state=unchecked]:border-text-secondary/75 data-[state=unchecked]:bg-surface-2",
      className,
    )}
    {...props}
    ref={ref}
  >
    <SwitchPrimitives.Thumb
      className={cn(
        "pointer-events-none block h-5 w-5 rounded-full bg-background elev-1 ring-0 transition-transform duration-base ease-enter data-[state=checked]:translate-x-5 data-[state=unchecked]:translate-x-0",
      )}
    />
  </SwitchPrimitives.Root>
));
Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
