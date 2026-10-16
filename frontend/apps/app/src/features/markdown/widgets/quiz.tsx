"use client";

import { Button } from "@v1/ui/button";
import { cn } from "@v1/ui/utils";
import { CircleCheck, CircleX, ListChecks, SkipForward, Trophy } from "lucide-react";
import { useContext, useEffect, useId, useRef, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import type { Assessment, AssessmentQuestion } from "@/lib/api/types";
import { LETTERS, testLocator } from "../assessment";
import { TestContext, type TestState } from "../context";
import { InlineMarkdown } from "../message-content";
import type { WidgetProps } from "../rich-block";
import { CardFrame } from "../study-card";
import { prefersReducedMotion } from "./tokens";

/**
 * The server's record for a practice block (app/assessments), shared by the test and exercise
 * cards: found by the block's locator in what the reply's metadata says. While the reply is still
 * being written there is none yet (`waiting`). A block with no record (an old reply, or one the
 * server could not accept) gives up, so the block's source shows with the reason.
 */
export function useRecord(source: string, onError: (note?: string) => void, noun: "test" | "exercise") {
  const tests = useContext(TestContext);
  // undefined while hashing; null when this browser cannot hash (the card then cannot bind).
  const [locator, setLocator] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    testLocator(source).then(
      (found) => alive && setLocator(found),
      () => alive && setLocator(null),
    );
    return () => {
      alive = false;
    };
  }, [source]);

  const record = locator ? tests?.assessments.find((item) => item.locator === locator) : undefined;
  const waiting = Boolean(tests?.streaming) || locator === undefined;
  const reason = tests?.error
    ? `This ${noun} couldn't be set up, so it can't be answered. Tap Regenerate for a new one.`
    : `This ${noun} can't be answered here (it was written before answers were saved). Ask for a new one.`;
  useEffect(() => {
    if (!waiting && !record) onError(reason);
  }, [waiting, record, reason, onError]);
  return { tests, record, waiting };
}

export function Preparing({ noun }: { noun: string }) {
  return (
    <p role="status" className="my-3 rounded-xl border border-border bg-study-card px-3.5 py-3 text-sm text-text-secondary">
      Preparing your {noun}…
    </p>
  );
}

export function failure(error: unknown, noun = "test"): string {
  if (error instanceof ApiError && error.status === 409) {
    return `This ${noun} moved on elsewhere (another tab?) or was replaced. It now shows where it is.`;
  }
  return "Your answer wasn't saved. Check your connection and try again.";
}

/**
 * ```mcq and ```quiz: a practice test the server keeps. The card draws only what the server
 * recorded for this reply: the questions, the answers given (final, graded there), the waiting
 * question and the score. Nothing is scored or remembered here; a reload shows the same.
 */
function TestBlock({ source, onError, single }: WidgetProps & { single: boolean }) {
  const { tests, record, waiting } = useRecord(source, onError, "test");
  if (waiting) return <Preparing noun="test" />;
  if (!record || !tests) return null;
  return <TestCard test={record} single={single} tests={tests} />;
}

function TestCard({ test, single, tests }: { test: Assessment; single: boolean; tests: TestState }) {
  const name = useId();
  const [chosen, setChosen] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const focus = useRef<HTMLDivElement>(null);
  // Scroll only after this card's own action (a tap here, or a typed command for this test), and
  // only as far as needed to show what comes next: never when the card first appears.
  const acted = useRef(false);
  const notice = tests.notice?.position === test.position ? tests.notice : null;
  const seenNotice = useRef(notice?.seq);
  const current = test.current;

  // A new waiting question starts unchosen.
  useEffect(() => setChosen(null), [current]);

  useEffect(() => {
    const typed = notice !== null && notice.seq !== seenNotice.current;
    if (typed) seenNotice.current = notice?.seq;
    if (!acted.current && !typed) return;
    acted.current = false;
    focus.current?.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [current, notice]);

  const respond = async (action: "answer" | "skip") => {
    if (current === null || saving || (action === "answer" && chosen === null)) return;
    setSaving(true);
    setProblem(null);
    acted.current = true;
    try {
      await tests.respond(test.position, {
        hash: test.hash,
        question: current,
        action,
        ...(action === "answer" && chosen !== null ? { value: chosen } : {}),
      });
    } catch (error) {
      acted.current = false;
      setProblem(failure(error));
    } finally {
      setSaving(false);
    }
  };

  const waiting = current === null ? null : test.questions[current];
  const lastAnswered = test.answered - 1;
  const last = test.questions[lastAnswered]?.response;
  // Read out after each response (a live region announces changes, not what a reload shows).
  const result = last
    ? `${single ? "" : `Question ${lastAnswered + 1}: `}${last.status === "skipped" ? "skipped" : last.earned ? "correct" : "not quite"}.`
    : "";
  return (
    <CardFrame
      kind={single ? "mcq" : "quiz"}
      icon={ListChecks}
      label={single ? "Multiple choice" : "Practice test"}
      title={test.title ?? undefined}
    >
      {!single && current !== null && (
        <p className="mb-2 text-xs font-medium text-text-secondary">
          Question {current + 1} of {test.total}
          {test.answered ? ` · ${test.earned} correct so far` : ""}
        </p>
      )}
      {test.questions.some((question) => question.response) && (
        <ol className={cn("space-y-2", waiting && "mb-3")}>
          {test.questions.map((question, index) =>
            question.response ? (
              // biome-ignore lint/suspicious/noArrayIndexKey: questions are positions in the test
              <Answered key={index} number={single ? null : index + 1} question={question} open={index === lastAnswered} />
            ) : null,
          )}
        </ol>
      )}
      <div ref={focus} className="scroll-my-4">
        {waiting && current !== null ? (
          <div>
            <fieldset className="min-w-0" disabled={!test.answerable || saving}>
              <legend className="mb-2 font-medium leading-6">
                {!single && <span className="mr-1 text-text-secondary">Q{current + 1}.</span>}
                <InlineMarkdown text={waiting.text ?? ""} />
              </legend>
              <div className="space-y-2">
                {(waiting.options ?? []).map((option, index) => (
                  <label
                    // biome-ignore lint/suspicious/noArrayIndexKey: options are positions in the question
                    key={index}
                    className={cn(
                      "flex min-h-11 cursor-pointer items-start gap-2.5 rounded-lg border bg-card px-3 py-2 text-sm leading-6 transition-colors hover:border-brand/50",
                      chosen === index ? "border-brand" : "border-border",
                    )}
                  >
                    <input
                      type="radio"
                      name={name}
                      checked={chosen === index}
                      onChange={() => setChosen(index)}
                      className="mt-1.5 shrink-0 accent-brand"
                    />
                    <span className="shrink-0 font-semibold">{LETTERS[index]}.</span>
                    <span className="min-w-0 flex-1 break-words">
                      <InlineMarkdown text={option} />
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            {test.answerable ? (
              <div className="mt-3 flex flex-wrap gap-2">
                <Button type="button" size="sm" disabled={chosen === null || saving} onClick={() => void respond("answer")}>
                  {saving ? "Saving…" : "Check answer"}
                </Button>
                <Button type="button" size="sm" variant="outline" disabled={saving} onClick={() => void respond("skip")}>
                  <SkipForward aria-hidden className="mr-1.5 h-3.5 w-3.5" />
                  Skip
                </Button>
              </div>
            ) : (
              <p className="mt-3 text-xs text-text-secondary">This test can no longer be answered.</p>
            )}
          </div>
        ) : !single ? (
          <p className="flex items-center gap-1.5 text-base font-semibold">
            <Trophy aria-hidden className="h-4 w-4 text-brand" />
            You scored {test.earned} out of {test.possible}.
          </p>
        ) : null}
      </div>
      <p role="status" className={cn("text-xs", problem || notice ? "mt-2" : "sr-only", problem ? "text-destructive" : "text-text-secondary")}>
        {problem ?? notice?.text ?? result}
      </p>
    </CardFrame>
  );
}

/** A question with its response: what was chosen, whether it was right, and why (compact). */
function Answered({ number, question, open }: { number: number | null; question: AssessmentQuestion; open: boolean }) {
  const response = question.response;
  if (!response || question.correct === null) return null;
  const right = `${LETTERS[question.correct]}. `;
  const correct = response.status === "answered" && response.earned > 0;
  return (
    <li className="rounded-lg border border-border bg-card px-3 py-2 text-sm leading-6">
      <p className="font-medium">
        {number !== null && <span className="mr-1 text-text-secondary">Q{number}.</span>}
        <InlineMarkdown text={question.text ?? ""} />
      </p>
      <p className="mt-1 flex items-start gap-1.5">
        {response.status === "skipped" ? (
          <SkipForward aria-hidden className="mt-1 h-4 w-4 shrink-0 text-text-secondary" />
        ) : correct ? (
          <CircleCheck aria-hidden className="mt-1 h-4 w-4 shrink-0 text-success" />
        ) : (
          <CircleX aria-hidden className="mt-1 h-4 w-4 shrink-0 text-destructive" />
        )}
        <span className="min-w-0 flex-1 break-words">
          {response.status === "skipped" ? (
            <>Skipped. The answer is {right}</>
          ) : correct ? (
            <>Correct! You chose {right}</>
          ) : (
            <>
              Not quite: you chose {LETTERS[typeof response.value === "number" ? response.value : 0]}, the answer is {right}
            </>
          )}
          <InlineMarkdown text={question.options?.[question.correct] ?? ""} />
        </span>
      </p>
      {question.explanation ? (
        <details open={open} className="mt-1 text-text-secondary">
          <summary className="cursor-pointer text-xs font-medium">Why</summary>
          <p className="mt-1 text-foreground">
            <InlineMarkdown text={question.explanation} />
          </p>
        </details>
      ) : null}
    </li>
  );
}

/** ```mcq: one multiple-choice question. */
export function McqBlock(props: WidgetProps) {
  return <TestBlock {...props} single />;
}

/** ```quiz: several questions, one at a time, then the score. */
export function QuizBlock(props: WidgetProps) {
  return <TestBlock {...props} single={false} />;
}

/**
 * ```question-bank: the tutor's request for a test from the question bank. The server replaces it
 * with the test before the reply is saved (app/qbank/chat_tests.py), so a saved reply still holding
 * one stopped before the test was set: say so, with the request's source.
 */
export function BankBlock({ onError }: WidgetProps) {
  useEffect(() => onError("The test wasn't set because the reply stopped. Ask for it again."), [onError]);
  return null;
}
