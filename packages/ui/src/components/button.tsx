import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";

import { cn } from "../utils";

const buttonVariants = cva(
  // `transition-all` rather than `transition-colors` so the press and the shadow
  // animate too; `active:scale-[0.98]` gives a button the small physical
  // acknowledgement that separates a product from a page.
  "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium ring-offset-background transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none",
  {
    variants: {
      variant: {
        // The primary action is the product's own green. It used to be
        // `bg-primary`, which in this codebase is the near-black TEXT colour —
        // so every call to action rendered as a black slab, the single biggest
        // reason the app read as unstyled.
        default:
          "bg-brand text-brand-foreground elev-1 hover:brightness-110 hover:elev-2",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline:
          "border border-input bg-background hover:border-brand/40 hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        // 44px on touch is the accessible minimum; the desktop breakpoint takes
        // it back to 40 where pointers are precise.
        default: "h-11 px-4 py-2 sm:h-10",
        sm: "h-9 rounded-md px-3",
        lg: "h-12 rounded-lg px-8 text-base sm:h-11",
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
