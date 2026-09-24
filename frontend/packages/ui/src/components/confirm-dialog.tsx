"use client";

import * as React from "react";

import { Button } from "./button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./dialog";

/**
 * "Are you sure?" — as a real dialog.
 *
 * WHY NOT `window.confirm`
 *
 * The app uses it to delete a chat, which is irreversible. A native confirm is
 * the wrong tool for that, for reasons that are not cosmetic:
 *
 *   - It BLOCKS the main thread. Nothing renders, no state updates, and on a
 *     slow machine the page appears frozen before the box paints.
 *   - It cannot say which chat. The browser renders plain text with no styling
 *     and no formatting, so "Delete this chat?" is as specific as it gets — the
 *     user confirms a deletion without seeing what they are deleting.
 *   - It is unstyled and unbranded, so the most consequential moment in the
 *     product looks the least like the product.
 *   - Some browsers let a user suppress further dialogs from a page. Once they
 *     do, `confirm()` silently returns false forever and the delete button stops
 *     working with no error.
 *
 * `destructive` is not just colour: it also moves focus to Cancel instead of the
 * confirm button, so Enter on a dialog you did not expect cannot delete
 * anything.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  pending = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  pending?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const cancelRef = React.useRef<HTMLButtonElement>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        // Radix focuses the first tabbable element by default, which for a
        // destructive dialog is the button that destroys something.
        onOpenAutoFocus={(event) => {
          if (!destructive) return;
          event.preventDefault();
          cancelRef.current?.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            ref={cancelRef}
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={destructive ? "destructive" : "default"}
            onClick={() => void onConfirm()}
            disabled={pending}
          >
            {pending ? "Working…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
