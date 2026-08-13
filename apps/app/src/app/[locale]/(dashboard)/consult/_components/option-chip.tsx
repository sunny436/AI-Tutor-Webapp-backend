"use client";

import { cn } from "@v1/ui/utils";
import { Check } from "lucide-react";
import type { ConsultOption } from "@/lib/consult/types";

/**
 * One tappable answer.
 *
 * Selection is shown three ways at once — fill, border and a tick — because
 * colour alone is not an accessible state indicator, and these are read at a
 * glance while someone is describing a symptom.
 */
export function OptionChip({
  option,
  single,
  selected,
  disabled,
  onToggle,
}: {
  option: ConsultOption;
  /** One-of question: announce a radio, not a checkbox. */
  single?: boolean;
  selected: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role={single ? "radio" : "checkbox"}
      aria-checked={selected}
      disabled={disabled}
      onClick={onToggle}
      // The planner marks options that mean "see a doctor rather than
      // self-manage". Selecting one ends the consultation with a referral, which
      // is correct — but it makes the option invisible to anything driving the UI
      // from outside. The E2E suites were tapping the first chip of each card and
      // hitting these by luck, then failing because the flow had (rightly) gone
      // somewhere else. Labels are model-written and now appear in Hinglish and
      // Devanagari too, so matching on text is not an option.
      data-red-flag={option.red_flag ? "true" : undefined}
      className={cn(
        "group inline-flex items-center gap-2 rounded-xl border px-3.5 py-2.5 text-sm font-medium transition-all",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        // `motion-safe:` on the lift only. The reduced-motion rule stops the
        // transition, but an untransitioned transform still snaps into place.
        "motion-safe:hover:-translate-y-0.5",
        selected
          ? option.red_flag
            ? "border-warning bg-warning text-background elev-2"
            : "border-brand bg-brand text-brand-foreground elev-2"
          : option.red_flag
            ? // A red-flag option ends the consultation in a referral to a
              // doctor. It looked EXACTLY like every other chip, so the single
              // most consequential thing a user can tap here — "I'm coughing
              // blood", "chest pain" — was visually indistinguishable from
              // "after meals". Amber, not red: this is "this needs attention",
              // not "you did something wrong", and red on a health form reads
              // as an error the reader has made.
              "border-warning/40 bg-warning-soft text-warning hover:border-warning/70"
            : "border-border bg-card text-text-secondary hover:border-brand/50 hover:text-brand hover:elev-1",
      )}
    >
      {option.emoji && <span aria-hidden>{option.emoji}</span>}
      <span>{option.label}</span>
      {/* Says out loud what the amber says visually. Colour is not an accessible
          indicator on its own, and this is the one distinction on the form that
          changes where the consultation ends up. */}
      {option.red_flag && <span className="sr-only"> — needs a doctor&apos;s attention</span>}
      <span
        aria-hidden
        className={cn(
          "grid h-4 w-4 shrink-0 place-items-center rounded-full transition-all",
          selected ? "bg-background/25" : "scale-0",
        )}
      >
        {selected && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
    </button>
  );
}
