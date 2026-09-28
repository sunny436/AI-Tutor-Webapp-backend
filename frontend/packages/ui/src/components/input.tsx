import * as React from "react";

import { cn } from "../utils";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

/**
 * Two of the changes here are not style preferences.
 *
 * `h-11 sm:h-10` and `text-base sm:text-sm`: iOS Safari zooms the page when a
 * focused input's font is under 16px, and does not zoom back out. The auth
 * forms already carried this rule in a hand-rolled 200-character class string;
 * the primitive did not, so every field that actually used <Input> — settings,
 * onboarding, change-password — still had the bug. 44px is also the accessible
 * touch minimum, matching Button's `default` size exactly.
 *
 * `.focus-field` rather than an offset ring: change-password stacks three
 * fields in a column, and an offset ring draws over the field above it.
 */
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-11 w-full rounded-xl border border-input bg-card px-3 py-2 text-base font-medium text-foreground transition-colors",
          "file:mr-3 file:h-7 file:rounded-md file:border-0 file:bg-surface-2 file:px-2.5 file:text-xs file:font-medium file:text-foreground",
          "placeholder:text-text-secondary",
          "focus-field",
          // A border-only field at 50% opacity is indistinguishable from an
          // empty one. A filled well says "disabled" without relying on it.
          "disabled:cursor-not-allowed disabled:bg-surface-2 disabled:opacity-60",
          "aria-[invalid=true]:border-destructive aria-[invalid=true]:ring-2 aria-[invalid=true]:ring-destructive/25",
          "sm:h-10 sm:text-sm",
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
