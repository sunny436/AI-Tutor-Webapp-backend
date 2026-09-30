"use client";

import { Button } from "@v1/ui/button";
import { cn } from "@v1/ui/utils";
import { CircleCheck, CircleX, ListChecks, RotateCcw, Trophy } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { z } from "zod";

import { InlineMarkdown } from "../message-content";
import type { WidgetProps } from "../rich-block";
import { CardFrame } from "../study-card";
import { parseJson } from "./tokens";

const Mcq = z.object({
  question: z.string().min(1).max(1000),
  options: z.array(z.string().min(1).max(400)).min(2).max(8),
  answer: z.union([z.string().max(400), z.number().int()]),
  explanation: z.string().max(2000).optional(),
});
type McqSpec = z.infer<typeof Mcq>;
const Quiz = z.object({ title: z.string().max(200).optional(), questions: z.array(Mcq).min(1).max(30) });

const LETTERS = "ABCDEFGH";

/** The right option's index: a letter ("B"), a 0-based number, or the option's own text. */
export function answerIndex(mcq: McqSpec): number {
  const { answer, options } = mcq;
  if (typeof answer === "number") return answer >= 0 && answer < options.length ? answer : -1;
  const text = answer.trim();
  const letter = /^\(?([A-Ha-h])[).:]?$/.exec(text)?.[1];
  if (letter) {
    const index = LETTERS.indexOf(letter.toUpperCase());
    return index < options.length ? index : -1;
  }
  return options.findIndex((option) => option.trim().toLowerCase() === text.toLowerCase());
}

function readMcq(source: string): McqSpec | null {
  const parsed = Mcq.safeParse(parseJson(source));
  return parsed.success && answerIndex(parsed.data) !== -1 ? parsed.data : null;
}

function readQuiz(source: string): z.infer<typeof Quiz> | null {
  const parsed = Quiz.safeParse(parseJson(source));
  return parsed.success && parsed.data.questions.every((question) => answerIndex(question) !== -1) ? parsed.data : null;
}

/** One question: choose, check, see why. Controlled, so a quiz can walk through several. */
function Question({
  mcq,
  chosen,
  checked,
  onChoose,
  onCheck,
}: {
  mcq: McqSpec;
  chosen: number | null;
  checked: boolean;
  onChoose: (index: number) => void;
  onCheck: () => void;
}) {
  const name = useId();
  const right = answerIndex(mcq);
  const correct = checked && chosen === right;
  return (
    <div>
      <fieldset className="min-w-0">
        <legend className="mb-2 font-medium leading-6">
          <InlineMarkdown text={mcq.question} />
        </legend>
        <div className="space-y-2">
          {mcq.options.map((option, index) => {
            const isRight = checked && index === right;
            const isWrong = checked && index === chosen && index !== right;
            return (
              <label
                // biome-ignore lint/suspicious/noArrayIndexKey: options are positions in the question
                key={index}
                className={cn(
                  "flex min-h-11 cursor-pointer items-start gap-2.5 rounded-lg border bg-card px-3 py-2 text-sm leading-6 transition-colors",
                  checked ? "cursor-default" : "hover:border-brand/50",
                  isRight ? "border-success" : isWrong ? "border-destructive" : chosen === index ? "border-brand" : "border-border",
                )}
              >
                <input
                  type="radio"
                  name={name}
                  checked={chosen === index}
                  disabled={checked}
                  onChange={() => onChoose(index)}
                  className="mt-1.5 shrink-0 accent-brand"
                />
                <span className="shrink-0 font-semibold">{LETTERS[index]}.</span>
                <span className="min-w-0 flex-1 break-words">
                  <InlineMarkdown text={option} />
                </span>
                {isRight && <CircleCheck aria-label="Correct answer" className="mt-1 h-4 w-4 shrink-0 text-success" />}
                {isWrong && <CircleX aria-label="Your answer" className="mt-1 h-4 w-4 shrink-0 text-destructive" />}
              </label>
            );
          })}
        </div>
      </fieldset>
      {!checked && (
        <Button type="button" size="sm" className="mt-3" disabled={chosen === null} onClick={onCheck}>
          Check answer
        </Button>
      )}
      {checked && (
        <div role="status" className="mt-3 text-sm leading-6">
          <p className="flex items-center gap-1.5 font-semibold">
            {correct ? (
              <CircleCheck aria-hidden className="h-4 w-4 text-success" />
            ) : (
              <CircleX aria-hidden className="h-4 w-4 text-destructive" />
            )}
            {correct ? "Correct!" : `Not quite: the answer is ${LETTERS[right]}.`}
          </p>
          {mcq.explanation ? (
            <p className="mt-1 text-foreground">
              <InlineMarkdown text={mcq.explanation} />
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}

/** ```mcq: one multiple-choice question. */
export function McqBlock({ source, onError }: WidgetProps) {
  const mcq = useMemo(() => readMcq(source), [source]);
  const [chosen, setChosen] = useState<number | null>(null);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    if (!mcq) onError();
  }, [mcq, onError]);
  if (!mcq) return null;
  return (
    <CardFrame kind="mcq" icon={ListChecks} label="Multiple choice">
      <Question mcq={mcq} chosen={chosen} checked={checked} onChoose={setChosen} onCheck={() => setChecked(true)} />
      {checked && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => {
            setChosen(null);
            setChecked(false);
          }}
        >
          <RotateCcw aria-hidden className="mr-1.5 h-3.5 w-3.5" />
          Try again
        </Button>
      )}
    </CardFrame>
  );
}

/** ```quiz: several questions, one at a time, then the score. */
export function QuizBlock({ source, onError }: WidgetProps) {
  const quiz = useMemo(() => readQuiz(source), [source]);
  const [at, setAt] = useState(0);
  const [chosen, setChosen] = useState<(number | null)[]>([]);
  const [checked, setChecked] = useState<boolean[]>([]);
  useEffect(() => {
    if (!quiz) onError();
  }, [quiz, onError]);
  if (!quiz) return null;

  const total = quiz.questions.length;
  const finished = at >= total;
  const score = quiz.questions.filter((question, index) => chosen[index] === answerIndex(question)).length;
  const restart = () => {
    setAt(0);
    setChosen([]);
    setChecked([]);
  };
  const current = quiz.questions[at];

  return (
    <CardFrame kind="quiz" icon={ListChecks} label="Quiz" title={quiz.title}>
      {finished || !current ? (
        <div role="status" className="text-sm leading-6">
          <p className="flex items-center gap-1.5 text-base font-semibold">
            <Trophy aria-hidden className="h-4 w-4 text-brand" />
            You scored {score} out of {total}.
          </p>
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={restart}>
            <RotateCcw aria-hidden className="mr-1.5 h-3.5 w-3.5" />
            Take it again
          </Button>
        </div>
      ) : (
        <>
          <p className="mb-2 text-xs font-medium text-text-secondary">
            Question {at + 1} of {total}
          </p>
          <Question
            key={at}
            mcq={current}
            chosen={chosen[at] ?? null}
            checked={Boolean(checked[at])}
            onChoose={(index) => setChosen((all) => Object.assign([...all], { [at]: index }))}
            onCheck={() => setChecked((all) => Object.assign([...all], { [at]: true }))}
          />
          {checked[at] && (
            <Button type="button" size="sm" className="mt-3" onClick={() => setAt(at + 1)}>
              {at + 1 < total ? "Next question" : "See my score"}
            </Button>
          )}
        </>
      )}
    </CardFrame>
  );
}
