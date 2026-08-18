"use client";

import { Button } from "@v1/ui/button";
import { Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import type { ConsultAnswer, IntakePlan, Selection } from "@/lib/consult/types";
import { answeredCount } from "@/lib/consult/types";
import { QuestionCard } from "./question-card";

/**
 * A whole round of intake — the screen that replaces the old
 * one-typed-question-at-a-time loop.
 *
 * Selections are held locally and only sent on "Continue", so tapping through
 * the form costs no network round-trips and the user can freely change their
 * mind before committing.
 */
export function IntakePanel({
  plan,
  initialSelection,
  pending,
  onSubmit,
}: {
  plan: IntakePlan;
  initialSelection?: Selection;
  pending: boolean;
  onSubmit: (selection: Selection) => void;
}) {
  const [selection, setSelection] = useState<Selection>(initialSelection ?? {});

  const total = plan.questions.length;
  const done = useMemo(
    () => answeredCount(plan.questions, selection),
    [plan.questions, selection],
  );
  const progress = total === 0 ? 0 : Math.round((done / total) * 100);

  const change = (questionId: string, next: ConsultAnswer) =>
    setSelection((current) => ({ ...current, [questionId]: next }));

  return (
    <div className="space-y-3">
      {/* Header + progress */}
      <div className="rounded-2xl border border-brand/20 bg-brand-soft/50 p-4">
        <div className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
          <Sparkles aria-hidden className="h-4 w-4 text-brand" />
          {plan.condition || "A few quick questions"}
        </div>
        {plan.note && (
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">{plan.note}</p>
        )}

        <div className="mt-3 flex items-center gap-3">
          {/* The bar is a picture of the count beside it, so it is described
              once, in words, rather than twice. */}
          <div
            aria-hidden
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-brand/15"
          >
            <div
              className="h-full rounded-full bg-brand transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="shrink-0 font-mono text-2xs font-medium tabular-nums text-text-secondary">
            <span aria-hidden>
              {done}/{total}
            </span>
            <span className="sr-only">
              {done} of {total} questions answered
            </span>
          </span>
        </div>
      </div>

      {plan.questions.map((question, index) => (
        <QuestionCard
          key={question.id}
          question={question}
          index={index}
          selection={selection}
          disabled={pending}
          onChange={change}
        />
      ))}

      {/* Nothing is mandatory — "Skip" exists so the user always keeps control
          and can get an answer without working through every card. */}
      <div className="flex items-center justify-between gap-3 pt-1">
        <button
          type="button"
          disabled={pending}
          onClick={() => onSubmit({})}
          className="text-xs text-text-secondary underline underline-offset-2 transition-colors hover:text-foreground disabled:opacity-50"
        >
          Skip — answer now
        </button>
        <Button type="button" disabled={pending} onClick={() => onSubmit(selection)}>
          {pending ? "Preparing your plan…" : done > 0 ? "Get my plan" : "Continue"}
        </Button>
      </div>
    </div>
  );
}
