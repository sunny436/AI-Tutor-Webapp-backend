"use client";

import { Button } from "@v1/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@v1/ui/dialog";
import { useState } from "react";

/** A destructive action button gated behind a confirm dialog. */
export function ConfirmButton({
  onConfirm,
  label,
  title = "Are you sure?",
  description,
  confirmLabel = "Confirm",
  // `text-red-500 underline` was a raw palette colour on a link-shaped
  // control. `--destructive` is the token, and it is tuned for both themes;
  // red-500 is not, and read as pink-on-charcoal in dark mode.
  className = "focus-ring rounded-md text-xs font-medium text-destructive underline-offset-2 hover:underline",
}: {
  onConfirm: () => Promise<void> | void;
  label: React.ReactNode;
  title?: string;
  description?: string;
  confirmLabel?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>
        {label}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && <DialogDescription>{description}</DialogDescription>}
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onConfirm();
                  setOpen(false);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "…" : confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
