import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";

import { cn } from "../utils";

const buttonVariants = cva(
  // Colour, shadow and the press animate (motion tokens: fast, standard), never layout;
  // `active:scale-[0.98]` gives a button the small physical acknowledgement that
  // separates a product from a page.
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold ring-offset-background transition-[color,background-color,border-color,box-shadow,transform,opacity] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none",
  {
    variants: {
      variant: {
        // The primary action is the product's slate blue on a hairline shadow (never a
        // coloured glow). Not `bg-primary`: in this codebase that is the near-black TEXT colour.
        default: "bg-brand text-brand-foreground elev-1 hover:bg-brand-hover",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        // Secondary: a white surface and a hairline, no shadow.
        outline:
          "border border-input bg-card text-foreground hover:border-brand/30 hover:bg-surface-2",
        secondary: "bg-secondary text-secondary-foreground hover:bg-border",
        ghost: "hover:bg-surface-2 hover:text-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        // 44px on touch is the accessible minimum; the desktop breakpoint takes
        // it back to 40 where pointers are precise.
        default: "h-11 px-4 py-2 sm:h-10",
        sm: "h-9 rounded-lg px-3 text-xs",
        lg: "h-12 rounded-xl px-8 text-base sm:h-11",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
