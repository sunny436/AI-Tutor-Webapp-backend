"use client";

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
  const done = useMemo(() => answeredCount(plan.questions, selection), [plan.questions, selection]);
  const progress = total === 0 ? 0 : Math.round((done / total) * 100);

  const change = (questionId: string, next: ConsultAnswer) =>
    setSelection((current) => ({ ...current, [questionId]: next }));

  return (
    <div className="space-y-3">
      {/* Header + progress */}
      <div className="rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/10 to-teal-500/5 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-primary">
          <Sparkles className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          {plan.condition || "A few quick questions"}
        </div>
        {plan.note && <p className="mt-1 text-sm leading-relaxed text-primary/70">{plan.note}</p>}

        <div className="mt-3 flex items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-emerald-500/15">
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="shrink-0 text-[11px] font-medium tabular-nums text-primary/50">
            {done}/{total}
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
          className="text-xs text-primary/50 underline underline-offset-2 transition hover:text-primary/80 disabled:opacity-50"
        >
          Skip — answer now
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => onSubmit(selection)}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 px-5 py-2.5 text-sm font-semibold text-white shadow-md shadow-emerald-500/25 transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? "Preparing your plan…" : done > 0 ? "Get my plan" : "Continue"}
        </button>
      </div>
    </div>
  );
}
