"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as React from "react";

import { cn } from "../utils";

/**
 * A panel that slides in from the edge — the mobile navigation drawer.
 *
 * Built on the Radix Dialog, so it gets what a hand-rolled drawer did not have:
 * a focus trap, `aria-modal`, Escape to close, focus returned to the button that
 * opened it, and the page behind made inert.
 */
const Sheet = DialogPrimitive.Root;
const SheetTrigger = DialogPrimitive.Trigger;
const SheetClose = DialogPrimitive.Close;
const SheetTitle = DialogPrimitive.Title;
const SheetDescription = DialogPrimitive.Description;

const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    side?: "left" | "right";
  }
>(({ className, children, side = "left", ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-overlay/55 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:duration-slow data-[state=open]:ease-enter data-[state=closed]:duration-fast data-[state=closed]:ease-exit" />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed inset-y-0 z-50 flex h-full max-w-[85vw] flex-col overscroll-contain bg-card elev-3 outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:duration-slow data-[state=open]:ease-enter data-[state=closed]:duration-fast data-[state=closed]:ease-exit",
        side === "left"
          ? "left-0 data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left"
          : "right-0 data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
        className,
      )}
      {...props}
    >
      {children}
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = "SheetContent";

export {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
};
