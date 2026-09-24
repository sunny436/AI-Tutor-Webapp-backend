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
import { Input } from "./input";

/**
 * Ask for one short string — a chat title, say.
 *
 * Replaces `window.prompt`. Beyond the blocking and styling problems described
 * in `confirm-dialog.tsx`, prompt has two of its own:
 *
 *   - No validation. It returns whatever was typed, including "" and 400
 *     characters of whitespace, and every caller has to re-check it.
 *   - No label association, no error text, no `maxLength`. It is a text field
 *     with none of the affordances of a text field.
 *
 * The form element is doing real work here: it makes Enter submit, which is what
 * everyone expects from a single-field dialog and what `prompt` gave for free.
 */
export function PromptDialog({
  open,
  onOpenChange,
  title,
  description,
  label,
  placeholder,
  initialValue = "",
  submitLabel = "Save",
  maxLength = 80,
  pending = false,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  label: string;
  placeholder?: string;
  initialValue?: string;
  submitLabel?: string;
  maxLength?: number;
  pending?: boolean;
  onSubmit: (value: string) => void | Promise<void>;
}) {
  const [value, setValue] = React.useState(initialValue);
  const fieldId = React.useId();

  // Re-seed when the dialog is opened for a different row. Without this, opening
  // "rename" on chat A, cancelling, then opening it on chat B would show A's
  // title — the component is mounted once and reused for every row.
  React.useEffect(() => {
    if (open) setValue(initialValue);
  }, [open, initialValue]);

  const trimmed = value.trim();
  const canSubmit = trimmed.length > 0 && !pending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            void onSubmit(trimmed);
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && (
              <DialogDescription>{description}</DialogDescription>
            )}
          </DialogHeader>

          <div className="py-4">
            {/* A real <label>, associated by id. `prompt` has no equivalent, so
                its text was never programmatically tied to its field. */}
            <label
              htmlFor={fieldId}
              className="mb-1.5 block text-sm font-medium"
            >
              {label}
            </label>
            <Input
              id={fieldId}
              value={value}
              placeholder={placeholder}
              maxLength={maxLength}
              autoComplete="off"
              // The one behaviour worth keeping from `prompt`: the existing value
              // arrives selected, so typing replaces it.
              // biome-ignore lint/a11y/noAutofocus: the dialog exists solely to collect this field
              autoFocus
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => setValue(event.target.value)}
            />
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {pending ? "Saving…" : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
