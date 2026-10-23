"use client";

import { Badge, type BadgeProps } from "@v1/ui/badge";
import { Button } from "@v1/ui/button";
import { EmptyState, ErrorState } from "@v1/ui/empty-state";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { CheckCircle2, ChevronDown, ClipboardList } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import { LazyInlineMarkdown } from "@/features/markdown/lazy-message-content";
import { useCatalog } from "@/features/settings/learning-data";
import { Notice } from "@/features/settings/primitives";
import { Panel, Stat } from "@/features/study/study-activity-view";
import { describeError } from "@/lib/api/errors";
import { getLearnerProfile } from "@/lib/api/learning";
import { getMastery, getMistakes, getPracticePlan, getPracticeTests, getRevisions } from "@/lib/api/progress";
import type {
  LearnerProfile,
  Mastery,
  MasteryState,
  MasterySubject,
  MistakeConcept,
  Mistakes,
  PlanTask,
  PracticePlan,
  PracticeTests,
  RevisionItem,
  Revisions,
} from "@/lib/api/types";
import { shortDate } from "@/lib/time";
import { useAskInChat } from "./ask-in-chat";
import { PracticePicker } from "./practice-picker";

const link = "focus-ring rounded font-semibold text-brand underline underline-offset-2";
const summary =
  "focus-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-foreground [&::-webkit-details-marker]:hidden";
const MISTAKES_SHOWN = 50;
const TESTS_SHOWN = 20;
const ASK_HINT = "Opens a new chat with your request filled in; nothing is sent until you press Send.";

type Variant = NonNullable<BadgeProps["variant"]>;

const STATES: Record<MasteryState, { label: string; badge: Variant }> = {
  mastered: { label: "Mastered", badge: "success" },
  learning: { label: "Learning", badge: "info" },
  weak: { label: "Needs work", badge: "warning" },
  not_enough_evidence: { label: "Not enough answers yet", badge: "neutral" },
};
const TASKS: Record<PlanTask["kind"], { label: string; badge: Variant; action: string }> = {
  revise: { label: "Revise", badge: "info", action: "Revise" },
  strengthen: { label: "Needs work", badge: "warning", action: "Practise" },
  learn: { label: "New", badge: "brand", action: "Practise" },
};
const REVISION_STATES: Record<RevisionItem["state"], { label: string; badge: Variant }> = {
  overdue: { label: "Overdue", badge: "danger" },
  due: { label: "Due today", badge: "info" },
  done: { label: "Revised today", badge: "success" },
  upcoming: { label: "Coming up", badge: "neutral" },
};

function days(count: number): string {
  return `${count} ${count === 1 ? "day" : "days"}`;
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/**
 * A subject's line, by its topics' rule: an estimate only once one of its topics has enough answers
 * for one (the API's subject mean also takes in concepts with too few answers).
 */
function subjectEstimate(subject: MasterySubject): string {
  const judged = subject.chapters.some((chapter) => chapter.topics.some((topic) => topic.state !== "not_enough_evidence"));
  return judged && subject.estimate !== null ? `estimate ${percent(subject.estimate)}` : "Not enough answers yet";
}

/** An India learning day ("YYYY-MM-DD"), as the day it names wherever the student is. */
function day(date: string): string {
  return new Date(`${date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function reason(task: PlanTask): string {
  switch (task.reason) {
    case "overdue":
      return `Revision is overdue by ${days(task.overdueDays ?? 0)}.`;
    case "due":
      return "Due for revision today.";
    case "weak_concept":
      return "Your recent answers show this needs more practice.";
    case "next_topic":
      return "The next topic you haven't practised yet.";
    case "start_here":
      return "A good place to start.";
  }
}

type Resource<T> = { data: T | null; error: unknown; retry: () => void };

/** One resource with its own loading, error and retry: a slow or failed panel never holds up the rest. */
function useResource<T>(load: (signal: AbortSignal) => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    load(controller.signal).then(
      (loaded) => !controller.signal.aborted && setData(loaded),
      (failure) => !controller.signal.aborted && setError(failure),
    );
    return () => controller.abort();
  }, [attempt]);
  return { data, error, retry: () => setAttempt((count) => count + 1) };
}

/** Loading (skeletons), a failure with Try again (never zeros), or the panel's content. */
function Loaded<T>({
  resource,
  what,
  children,
}: {
  resource: Resource<T>;
  what: string;
  children: (data: T) => ReactNode;
}) {
  if (resource.error) {
    return (
      <ErrorState
        title={`Couldn't load ${what}`}
        description={describeError(resource.error).message}
        action={
          <Button variant="outline" onClick={resource.retry}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!resource.data) {
    return (
      <SkeletonGroup label={`Loading ${what}`} className="space-y-3">
        <Skeleton className="h-16 w-full rounded-xl" />
        <Skeleton className="h-16 w-full rounded-xl" />
      </SkeletonGroup>
    );
  }
  return <>{children(resource.data)}</>;
}

/** A row's action: fills a new chat with its request (`name` is its accessible name). Full width on phones. */
function AskButton({ label, name, request, hint }: { label: string; name: string; request: string; hint: string }) {
  const ask = useAskInChat();
  return (
    <Button
      variant="outline"
      onClick={() => ask(request)}
      aria-label={name}
      aria-describedby={hint}
      className="w-full shrink-0 sm:w-auto"
    >
      {label}
    </Button>
  );
}

function Plan({ plan, subjectName }: { plan: PracticePlan; subjectName: (code: string) => string }) {
  const hint = useId();
  return (
    <div className="flex flex-col gap-4">
      {plan.needsProfile && (
        <Notice>
          To suggest new topics from your own subjects, the plan needs your class (6 to 12) in{" "}
          <Link href="/settings/academic" className={link}>
            Academic Profile
          </Link>{" "}
          and your subjects in{" "}
          <Link href="/settings/subjects" className={link}>
            Subjects & Study
          </Link>
          .
        </Notice>
      )}
      {plan.tasks.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title={plan.summary.answered ? "Nothing planned for today" : "No plan yet"}
          description={
            plan.summary.answered
              ? "Nothing is due for revision and no new topic is waiting. You can practise any chapter under Practice by chapter."
              : "Your plan comes from the question-bank tests you take in the chat. Choose a chapter under Practice by chapter to take your first one."
          }
          action={null}
        />
      ) : (
        <>
          {plan.insufficientHistory && (
            <p className="text-sm text-text-secondary">
              There are only a few answers to go on so far, so this plan is a starting point: it adapts as you answer more test
              questions.
            </p>
          )}
          <ol className="flex flex-col divide-y divide-border">
            {plan.tasks.map((task) => (
              <li
                key={`${task.kind}:${task.topicId}:${task.conceptTag ?? ""}`}
                className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={TASKS[task.kind].badge}>{TASKS[task.kind].label}</Badge>
                    <span className="min-w-0 break-words text-sm font-semibold text-foreground">{task.topicTitle}</span>
                  </div>
                  <p className="break-words text-xs text-text-secondary">
                    {subjectName(task.subjectCode)} · Chapter {task.chapterNumber}: {task.chapterTitle}
                  </p>
                  <p className="text-xs text-text-secondary">
                    {reason(task)} About {task.minutes} min, {task.questions} questions.
                  </p>
                  {task.done && (
                    <p className="flex items-center gap-1.5 text-xs font-semibold text-success">
                      <CheckCircle2 aria-hidden className="h-4 w-4" />
                      Done today
                    </p>
                  )}
                </div>
                <AskButton
                  label={TASKS[task.kind].action}
                  name={`${TASKS[task.kind].action} ${task.topicTitle} in a new chat`}
                  request={task.prompt}
                  hint={hint}
                />
              </li>
            ))}
          </ol>
          <p id={hint} className="text-2xs text-text-secondary">
            {ASK_HINT}
          </p>
        </>
      )}
      <dl className="grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-2">
        {plan.answeredToday >= plan.answersForLearningDay ? (
          <Stat
            value={String(plan.answeredToday)}
            label="test answers today"
            hint="Enough to make today a learning day for your streak."
          />
        ) : (
          <Stat
            value={`${plan.answeredToday} of ${plan.answersForLearningDay}`}
            label="test answers today"
            hint={`${plan.answersForLearningDay} make today a learning day for your streak, as a question answered in the chat does.`}
          />
        )}
        {plan.tasks.length > 0 && (
          <Stat
            value={`${plan.budgetMinutes} min`}
            label="planned for today"
            hint={plan.budgetSource === "goal" ? "Your daily goal from Learning Goals." : "Set a daily goal in Learning Goals to change it."}
          />
        )}
      </dl>
    </div>
  );
}

function RevisionRow({ item, subjectName, hint }: { item: RevisionItem; subjectName: (code: string) => string; hint?: string }) {
  const state = REVISION_STATES[item.state];
  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={state.badge}>{state.label}</Badge>
          <span className="min-w-0 break-words text-sm font-semibold text-foreground">{item.topicTitle}</span>
        </div>
        <p className="break-words text-xs text-text-secondary">
          {subjectName(item.subjectCode)} · Chapter {item.chapterNumber}: {item.chapterTitle}
        </p>
        <p className="text-xs text-text-secondary">
          {item.state === "overdue" ? `Due ${day(item.dueDate)}, ${days(item.overdueDays)} ago.` : `Due ${day(item.dueDate)}.`}{" "}
          Last time {percent(item.lastAccuracy)} right ({day(item.lastReviewed)}).
        </p>
      </div>
      {hint && <AskButton label="Revise" name={`Revise ${item.topicTitle} in a new chat`} request={item.prompt} hint={hint} />}
    </li>
  );
}

function Revision({ revisions, subjectName }: { revisions: Revisions; subjectName: (code: string) => string }) {
  const hint = useId();
  const now = revisions.items.filter((item) => item.state !== "upcoming");
  const later = revisions.items.filter((item) => item.state === "upcoming");
  if (!revisions.items.length) {
    return (
      <p className="text-sm text-text-secondary">
        Nothing to revise yet. A topic you practise comes back for revision after {revisions.ladderDays.join(", ")} days, a
        longer gap each time you remember it.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {now.length ? (
        <ul className="flex flex-col divide-y divide-border">
          {now.map((item) => (
            <RevisionRow
              key={item.topicId}
              item={item}
              subjectName={subjectName}
              hint={item.state === "overdue" || item.state === "due" ? hint : undefined}
            />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-text-secondary">Nothing is due today.</p>
      )}
      {now.some((item) => item.state === "overdue" || item.state === "due") && (
        <p id={hint} className="text-2xs text-text-secondary">
          {ASK_HINT}
        </p>
      )}
      {later.length > 0 && (
        <details className="group rounded-xl border border-border">
          <summary className={summary}>
            Coming up ({later.length})
            <ChevronDown aria-hidden className="h-4 w-4 shrink-0 text-text-secondary transition-transform group-open:rotate-180" />
          </summary>
          <ul className="flex flex-col divide-y divide-border px-3 pb-3">
            {later.map((item) => (
              <RevisionRow key={item.topicId} item={item} subjectName={subjectName} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ExamDate({ profile, plan }: { profile: LearnerProfile; plan: PracticePlan | null }) {
  // Days left as the server counts them (India days), once the plan for this same date is in. A
  // date that has passed has none, so that is read from the plan's own day (India).
  const left = plan && plan.examDate === profile.examDate ? plan.daysToExam : null;
  const passed = plan !== null && profile.examDate !== null && profile.examDate < plan.date;
  return (
    <div className="flex flex-col gap-3">
      {profile.examDate ? (
        <dl>
          <Stat
            value={day(profile.examDate)}
            label={profile.targetExam ?? "your exam"}
            hint={
              passed
                ? "This date has passed: set your next exam."
                : left === null
                  ? undefined
                  : left > 0
                    ? `In ${days(left)}.`
                    : "The exam is today. All the best!"
            }
          />
        </dl>
      ) : (
        <p className="text-sm text-text-secondary">
          {profile.targetExam ? `You're preparing for ${profile.targetExam}. ` : ""}
          No exam date is set. With one, the plan turns to revision as the exam gets close.
        </p>
      )}
      <Link href="/settings/goals" className={`${link} self-start text-sm`}>
        {profile.examDate ? "Change in Learning Goals" : "Set it in Learning Goals"}
      </Link>
    </div>
  );
}

function MasteryList({ mastery, subjectName }: { mastery: Mastery; subjectName: (code: string) => string }) {
  if (!mastery.subjects.length) {
    return (
      <p className="text-sm text-text-secondary">
        No estimates yet. They appear once you've answered questions in a test from the question bank.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col divide-y divide-border rounded-xl border border-border">
        {mastery.subjects.map((subject) => (
          <details key={`${subject.subjectCode}:${subject.classLevel}:${subject.language}`} className="group">
            <summary className={summary}>
              <span className="min-w-0 break-words">
                {subjectName(subject.subjectCode)}, Class {subject.classLevel}
              </span>
              <span className="flex shrink-0 items-center gap-2 text-xs font-medium text-text-secondary">
                {subjectEstimate(subject)}
                <ChevronDown aria-hidden className="h-4 w-4 transition-transform group-open:rotate-180" />
              </span>
            </summary>
            <div className="flex flex-col gap-4 px-3 pb-4">
              {subject.chapters.map((chapter) => (
                <section key={chapter.chapterId} aria-labelledby={`mastery-${chapter.chapterId}`} className="flex flex-col gap-2">
                  <h3 id={`mastery-${chapter.chapterId}`} className="break-words text-sm font-semibold text-foreground">
                    Chapter {chapter.number}: {chapter.title}
                    <span className="block text-xs font-normal text-text-secondary">{chapter.bookTitle}</span>
                  </h3>
                  <ul className="flex flex-col gap-2.5">
                    {chapter.topics.map((topic) => {
                      const answered = topic.concepts.reduce((sum, concept) => sum + concept.answered, 0);
                      const correct = topic.concepts.reduce((sum, concept) => sum + concept.correct, 0);
                      const shown = topic.state === "not_enough_evidence" ? null : topic.estimate;
                      return (
                        <li key={topic.topicId} className="flex flex-col gap-1">
                          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
                            <span className="min-w-0 break-words text-foreground">
                              {topic.number}. {topic.title}
                            </span>
                            <Badge variant={STATES[topic.state].badge}>{STATES[topic.state].label}</Badge>
                          </div>
                          <p className="text-xs text-text-secondary">
                            {correct} of {answered} correct
                            {shown === null ? "" : ` · estimate ${percent(shown)}`}
                          </p>
                          {shown !== null && (
                            <div aria-hidden className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                              <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(shown * 100, 2)}%` }} />
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          </details>
        ))}
      </div>
      <p className="text-2xs leading-relaxed text-text-secondary">
        An estimate is how likely you are to know a topic now, worked out from your test answers: a guide, not a mark. A
        concept needs at least {mastery.model.minAnswers} answers to {mastery.model.minQuestions} different questions before
        it can count as mastered.
      </p>
    </div>
  );
}

function MistakeEntry({ concept, subjectName, hint }: { concept: MistakeConcept; subjectName: (code: string) => string; hint: string }) {
  const option = (letter: string, options: string[]) => `${letter}. ${options["ABCD".indexOf(letter)] ?? ""}`;
  const what = concept.objective || concept.topicTitle;
  return (
    <details className="group">
      <summary className={summary}>
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="break-words">{what}</span>
          <span className="break-words text-xs font-normal text-text-secondary">
            {subjectName(concept.subjectCode)} · {concept.topicTitle} · wrong {concept.wrong}{" "}
            {concept.wrong === 1 ? "time" : "times"}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {concept.recurring && <Badge variant="warning">Recurring</Badge>}
          <ChevronDown aria-hidden className="h-4 w-4 text-text-secondary transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div className="flex flex-col gap-4 px-3 pb-4">
        <ul className="flex flex-col gap-4">
          {concept.items.map((item) => (
            <li key={`${item.questionId}:${item.answeredAt}`} className="flex min-w-0 flex-col gap-1.5 text-sm">
              {/* Wide maths scrolls here instead of widening the page. */}
              <div
                // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard-focusable to be scrollable
                tabIndex={0}
                role="region"
                aria-label="Question"
                className="scrollbar-subtle focus-ring-inset flex min-w-0 flex-col gap-1.5 overflow-x-auto break-words"
              >
                <p className="text-foreground">
                  <LazyInlineMarkdown text={item.stem} />
                </p>
                <p className="text-text-secondary">
                  Your answer: <LazyInlineMarkdown text={option(item.chosen, item.options)} />
                </p>
                <p className="text-foreground">
                  Correct answer: <LazyInlineMarkdown text={option(item.correct, item.options)} />
                </p>
                {item.explanation && (
                  <p className="text-text-secondary">
                    <LazyInlineMarkdown text={item.explanation} />
                  </p>
                )}
              </div>
              <p className="text-xs text-text-secondary">
                {shortDate(item.answeredAt)}
                {item.conversationId && (
                  <>
                    {" · "}
                    <Link href={`/c/${item.conversationId}`} className={link}>
                      Open the test
                    </Link>
                  </>
                )}
              </p>
            </li>
          ))}
        </ul>
        <AskButton label="Practise this" name={`Practise this in a new chat: ${what}`} request={concept.prompt} hint={hint} />
      </div>
    </details>
  );
}

function MistakeList({ mistakes, subjectName }: { mistakes: Mistakes; subjectName: (code: string) => string }) {
  const hint = useId();
  if (!mistakes.concepts.length) {
    return (
      <p className="text-sm text-text-secondary">
        No mistakes to review. A question you get wrong in a test shows up here, with the right answer.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col divide-y divide-border rounded-xl border border-border">
        {mistakes.concepts.map((concept) => (
          <MistakeEntry key={`${concept.topicId}:${concept.conceptTag}`} concept={concept} subjectName={subjectName} hint={hint} />
        ))}
      </div>
      <p className="text-2xs leading-relaxed text-text-secondary">
        Recurring: wrong {mistakes.recurringRule.wrong} or more times in {mistakes.recurringRule.days} days.
      </p>
      <p id={hint} className="text-2xs leading-relaxed text-text-secondary">
        {ASK_HINT}
      </p>
    </div>
  );
}

function TestList({ tests }: { tests: PracticeTests }) {
  if (!tests.items.length) {
    return (
      <p className="text-sm text-text-secondary">
        No tests yet. Ask the tutor for a test on a chapter, or choose one under Practice by chapter.
      </p>
    );
  }
  return (
    <ul className="flex flex-col divide-y divide-border">
      {tests.items.map((test) => (
        <li key={test.setId} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
            <span className="min-w-0 break-words font-semibold text-foreground">{test.title}</span>
            <span className="shrink-0 tabular-nums text-text-secondary">
              {test.answered ? `${test.correct} of ${test.answered} correct` : "No answers yet"}
            </span>
          </div>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
            {shortDate(test.startedAt)} · {test.answered} of {test.total} answered
            {test.open && <Badge variant="info">In progress</Badge>}
            {test.conversationId ? (
              <Link href={`/c/${test.conversationId}`} className={link}>
                Open the chat
              </Link>
            ) : (
              <span>(chat deleted)</span>
            )}
          </p>
        </li>
      ))}
    </ul>
  );
}

/**
 * My Learning: the student's own practice record, from question-bank tests in the chat only (GET
 * /v1/progress/plan, mastery, revisions, mistakes, practice-tests and practice-topics): today's plan,
 * a chapter picker, revision, the exam date, mastery estimates, mistakes and recent tests. Each panel
 * loads on its own, says when it can't, and never shows a number the server didn't give. Its
 * buttons fill a new chat with a request; nothing is sent until the student presses Send.
 */
export function MyLearningView() {
  const { catalog } = useCatalog();
  const plan = useResource(getPracticePlan);
  const mastery = useResource(getMastery);
  const revisions = useResource(getRevisions);
  const mistakes = useResource((signal) => getMistakes(MISTAKES_SHOWN, signal));
  const tests = useResource((signal) => getPracticeTests(TESTS_SHOWN, signal));
  const profile = useResource(() => getLearnerProfile());

  const subjectName = (code: string) => catalog?.subjects.find((entry) => entry.code === code)?.name ?? code;
  // The panels under the plan show once it has answered, and then stay (retrying a failed plan never hides them).
  const planAnswered = useRef(false);
  if (plan.data || plan.error) planAnswered.current = true;

  return (
    <div
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard-focusable to be scrollable
      tabIndex={0}
      role="region"
      aria-label="My Learning"
      className="scrollbar-subtle focus-ring-inset h-full overflow-y-auto"
    >
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6">
        <Panel id="learning-plan" title="Today's plan">
          <Loaded resource={plan} what="your plan">
            {(data) => <Plan plan={data} subjectName={subjectName} />}
          </Loaded>
        </Panel>

        {/* The rest shows once the plan has answered. Drawn under the plan's two-line skeleton, a plan
            arriving taller pushed every panel down (a layout shift of 0.61 on a phone, 2026-10-23); they
            are mounted from the start, hidden, so their requests (the chapters' too) run at once. */}
        <div className={planAnswered.current ? "contents" : "hidden"}>
          <Panel id="learning-practice" title="Practice by chapter">
            <PracticePicker subjectName={subjectName} />
          </Panel>

          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <Panel id="learning-revision" title="Revision due">
              <Loaded resource={revisions} what="your revision">
                {(data) => <Revision revisions={data} subjectName={subjectName} />}
              </Loaded>
            </Panel>
            <Panel id="learning-exam" title="Exam date">
              <Loaded resource={profile} what="your exam date">
                {(data) => <ExamDate profile={data} plan={plan.data} />}
              </Loaded>
            </Panel>
          </div>

          <Panel id="learning-mastery" title="Mastery">
            <Loaded resource={mastery} what="your mastery">
              {(data) => <MasteryList mastery={data} subjectName={subjectName} />}
            </Loaded>
          </Panel>

          <Panel id="learning-mistakes" title="Mistakes">
            <Loaded resource={mistakes} what="your mistakes">
              {(data) => <MistakeList mistakes={data} subjectName={subjectName} />}
            </Loaded>
          </Panel>

          <Panel id="learning-tests" title="Recent tests">
            <Loaded resource={tests} what="your tests">
              {(data) => <TestList tests={data} />}
            </Loaded>
          </Panel>

          <p className="text-xs leading-relaxed text-text-secondary">
            Everything here comes only from your answers to question-bank tests in the chat: flashcards and exercises the
            tutor writes itself are not counted. Only you can see it. Your study time is in{" "}
            <Link href="/study" className={link}>
              Study Activity
            </Link>
            .
          </p>
        </div>
      </div>
    </div>
  );
}
