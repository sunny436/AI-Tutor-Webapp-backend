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
        "disabled:cursor-not-allowed disabled:opacity-50",
        selected
          ? "border-emerald-500 bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/25"
          : "border-border bg-white/70 text-primary/75 hover:-translate-y-0.5 hover:border-emerald-500/50 hover:text-emerald-700 hover:shadow-sm dark:bg-white/[0.04] dark:hover:text-emerald-300",
      )}
    >
      {option.emoji && <span aria-hidden>{option.emoji}</span>}
      <span>{option.label}</span>
      <span
        className={cn(
          "grid h-4 w-4 shrink-0 place-items-center rounded-full transition-all",
          selected ? "bg-white/25" : "scale-0",
        )}
      >
        {selected && <Check aria-hidden className="h-3 w-3" strokeWidth={3} />}
      </span>
    </button>
  );
}
