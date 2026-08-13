"use client";

import { cn } from "@v1/ui/utils";
import { CheckCircle2 } from "lucide-react";
import type { ConsultQuestion, Selection } from "@/lib/consult/types";
import { isAnswered } from "@/lib/consult/types";
import { OptionChip } from "./option-chip";

/**
 * One question, rendered as tappable options.
 *
 * `display` is purely a rendering hint from the planner — "scale" lays ordered
 * intensity options out in a single row so the progression reads left-to-right,
 * "chips" wraps freely. The underlying data is identical, which is why the
 * backend only has three question types.
 */
export function QuestionCard({
  question,
  index,
  selection,
  disabled,
  onChange,
}: {
  question: ConsultQuestion;
  index: number;
  selection: Selection;
  disabled?: boolean;
  onChange: (questionId: string, next: { options: string[]; text?: string | null }) => void;
}) {
  const answer = selection[question.id] ?? { options: [], text: null };
  const answered = isAnswered(question, selection);

  // Question ids are written by the model, so they can contain anything. An id
  // attribute may not contain whitespace, and `aria-labelledby` is a
  // space-separated token list — one stray space would silently point at two
  // elements that do not exist and leave the card unlabelled again.
  const slug = question.id.replace(/\s+/g, "-");
  const labelId = `q-${slug}-label`;
  const hintId = `q-${slug}-hint`;
  const hint = question.hint || (question.type === "multi" ? "Pick all that apply" : "");

  const toggle = (optionId: string) => {
    if (question.type === "single") {
      // Tapping the chosen option again clears it — everything is skippable.
      const next = answer.options[0] === optionId ? [] : [optionId];
      onChange(question.id, { ...answer, options: next });
      return;
    }
    const has = answer.options.includes(optionId);
    let next = has
      ? answer.options.filter((id) => id !== optionId)
      : [...answer.options, optionId];
    if (!has && question.max_select && next.length > question.max_select) {
      // Drop the oldest so the newest tap always registers.
      next = next.slice(next.length - question.max_select);
    }
    onChange(question.id, { ...answer, options: next });
  };

  return (
    <div
      // Without this the options were announced as a bare row of checkboxes with
      // no indication of what they were answering — the question text sat in a
      // <p> that nothing referred to.
      role="group"
      aria-labelledby={labelId}
      aria-describedby={hint ? hintId : undefined}
      className={cn(
        "rounded-2xl border bg-white/70 p-4 shadow-sm backdrop-blur transition-colors dark:bg-white/[0.04]",
        "animate-in fade-in slide-in-from-bottom-2 fill-mode-both duration-500",
        answered ? "border-emerald-500/40" : "border-border",
      )}
      // Cards reveal in sequence rather than all at once, so a five-question
      // form reads as a conversation instead of a wall of controls.
      style={{ animationDelay: `${Math.min(index, 6) * 70}ms` }}
    >
      <div className="mb-3 flex items-start gap-2.5">
        <span
          className={cn(
            "mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg text-xs font-bold transition-colors",
            answered
              ? "bg-emerald-500 text-white"
              : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
          )}
        >
          {/* The number and the tick are decoration for the label beside them;
              read aloud they would prefix every question with a digit. The
              answered state is carried in words instead, in the label. */}
          {answered ? (
            <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <span aria-hidden>{index + 1}</span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p id={labelId} className="text-sm font-semibold leading-snug text-primary">
            {question.label}
            {answered && <span className="sr-only"> — answered</span>}
          </p>
          {hint && (
            <p id={hintId} className="mt-0.5 text-xs text-primary/45">
              {hint}
            </p>
          )}
        </div>
      </div>

      {question.type === "text" ? (
        <textarea
          rows={2}
          aria-labelledby={labelId}
          aria-describedby={hint ? hintId : undefined}
          disabled={disabled}
          value={answer.text ?? ""}
          onChange={(e) => onChange(question.id, { ...answer, text: e.target.value })}
          placeholder="Type here (optional)…"
          className="w-full resize-none rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none transition focus:border-emerald-500/60 focus:ring-2 focus:ring-emerald-500/20"
        />
      ) : (
        <div
          // "single" and "multi" are genuinely different controls and were both
          // announced as checkboxes, which tells someone they may pick several
          // when only one will register. Arrow-key roving is deliberately NOT
          // added with it: every chip stays in the tab order, exactly as before,
          // so no existing keyboard habit breaks.
          role={question.type === "single" ? "radiogroup" : "group"}
          aria-labelledby={labelId}
          aria-describedby={hint ? hintId : undefined}
          className={cn(
            "flex gap-2",
            question.display === "scale" ? "flex-nowrap overflow-x-auto pb-1" : "flex-wrap",
          )}
        >
          {question.options.map((option) => (
            <OptionChip
              key={option.id}
              option={option}
              single={question.type === "single"}
              selected={answer.options.includes(option.id)}
              disabled={disabled}
              onToggle={() => toggle(option.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
