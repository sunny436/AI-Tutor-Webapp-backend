"use client";

import { Button } from "@v1/ui/button";
import { Input } from "@v1/ui/input";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { X } from "lucide-react";
import { type KeyboardEvent, useId, useState } from "react";

import { describeError } from "@/lib/api/errors";
import {
  DAILY_MINUTES_MAX,
  EXAM_DATE_MAX_DAYS,
  GOAL_MAX,
  type LearnerProfileField,
  MAIN_GOALS,
  type MainGoal,
  TARGET_EXAM_MAX,
  TOPICS_MAX,
  TOPIC_MAX,
  WEEKLY_MINUTES_MAX,
} from "@/lib/api/types";
import { MAIN_GOAL_LABELS } from "./learning-labels";
import { addTopic } from "./learning-model";
import { Field, Notice, SectionHeading, SettingsCard } from "./primitives";
import { SaveFooter, selectClass, useProfileForm } from "./profile-form";

const FIELDS = [
  "mainGoal",
  "targetExam",
  "examDate",
  "targetScorePercent",
  "weakTopics",
  "dailyActiveMinutesGoal",
  "weeklyActiveMinutesGoal",
  "preferredStudyTime",
  "shortTermGoal",
  "longTermGoal",
] as const satisfies readonly LearnerProfileField[];

/** "YYYY-MM-DD" of the day `offset` days from today, on this device's calendar. */
function localDay(offset = 0): string {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** "YYYY-MM-DD" of the day `offset` days from today in UTC, the calendar the API checks an exam date on. */
function utcDay(offset: number): string {
  return new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
}

/** A whole number within [0, max], or null for empty. */
function wholeNumber(text: string, max: number): number | null {
  if (text.trim() === "") return null;
  const value = Math.round(Number(text));
  return Number.isFinite(value) ? Math.min(Math.max(value, 0), max) : null;
}

function TopicsEditor({
  topics,
  onChange,
  invalid,
}: {
  topics: string[];
  onChange: (topics: string[]) => void;
  invalid: boolean;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const listId = useId();

  const add = () => {
    const result = addTopic(topics, text, { max: TOPICS_MAX, maxLength: TOPIC_MAX });
    setError(result.error);
    if (!result.error) {
      onChange(result.topics);
      setText("");
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault(); // Enter adds the topic; it does not submit the whole form
      add();
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <Field
        label="Topics you find difficult"
        hint={`Up to ${TOPICS_MAX}. The tutor takes extra care with these.`}
        error={error ?? (invalid ? "Check these topics." : null)}
      >
        {(props) => (
          <div className="flex w-full gap-2 sm:max-w-[28rem]">
            <Input
              {...props}
              value={text}
              maxLength={TOPIC_MAX}
              placeholder="e.g. Trigonometry"
              onChange={(event) => setText(event.target.value)}
              onKeyDown={onKeyDown}
              aria-controls={listId}
            />
            <Button type="button" size="sm" variant="outline" onClick={add} disabled={!text.trim() || topics.length >= TOPICS_MAX}>
              Add
            </Button>
          </div>
        )}
      </Field>
      <ul id={listId} aria-label="Your difficult topics" className="flex flex-wrap gap-2">
        {topics.map((topic) => (
          <li
            key={topic}
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface-2 py-1 pl-3 pr-1 text-sm text-foreground"
          >
            {topic}
            <button
              type="button"
              onClick={() => onChange(topics.filter((item) => item !== topic))}
              aria-label={`Remove ${topic}`}
              className="focus-ring grid h-6 w-6 place-items-center rounded-md text-text-secondary hover:bg-border hover:text-foreground"
            >
              <X aria-hidden className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function GoalsSection() {
  const form = useProfileForm(FIELDS, "Goals saved.");
  const draft = form.draft;
  const check = (field: LearnerProfileField) => (form.invalid(field) ? "Check this value." : null);
  const today = localDay();

  return (
    <>
      <SectionHeading
        title="Learning Goals"
        description="What you're working towards. The tutor keeps it in mind; reminders and Progress use your study time and goals."
      />
      {form.loadError ? (
        <SettingsCard title="Couldn't load your goals">
          <p className="text-sm text-text-secondary">{describeError(form.loadError).message}</p>
          <button
            type="button"
            onClick={form.retry}
            className="focus-ring self-start rounded text-sm font-medium text-brand underline underline-offset-2"
          >
            Try again
          </button>
        </SettingsCard>
      ) : !draft ? (
        <SkeletonGroup label="Loading your goals">
          <Skeleton className="h-96 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <form onSubmit={form.submit} className="flex flex-col gap-4">
          {form.notice && <Notice tone="warning">{form.notice}</Notice>}
          <SettingsCard title="Your goals">
            <Field label="Main goal" error={check("mainGoal")}>
              {(props) => (
                <select
                  {...props}
                  value={draft.mainGoal ?? ""}
                  onChange={(event) => form.change({ mainGoal: (event.target.value || null) as MainGoal | null })}
                  className={selectClass}
                >
                  <option value="">Not set</option>
                  {MAIN_GOALS.map((goal) => (
                    <option key={goal} value={goal}>
                      {MAIN_GOAL_LABELS[goal]}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Exam you're preparing for" hint="For example: CBSE Class 10 boards, NEET, JEE Main." error={check("targetExam")}>
              {(props) => (
                <Input
                  {...props}
                  className="w-full sm:max-w-[20rem]"
                  value={draft.targetExam ?? ""}
                  maxLength={TARGET_EXAM_MAX}
                  onChange={(event) => form.change({ targetExam: event.target.value })}
                />
              )}
            </Field>
            <Field
              label="Exam date"
              hint="Optional. As it gets close, your plan in My Learning turns to revision."
              error={check("examDate")}
            >
              {(props) => (
                <Input
                  {...props}
                  className="w-full sm:w-44"
                  type="date"
                  // A new date is from today; one that has passed is left as it is, so saving the
                  // other goals never stops at it. The last day is the API's (UTC), which this
                  // device's calendar may already be a day past.
                  min={draft.examDate && draft.examDate < today ? undefined : today}
                  max={utcDay(EXAM_DATE_MAX_DAYS)}
                  value={draft.examDate ?? ""}
                  onChange={(event) => form.change({ examDate: event.target.value || null })}
                />
              )}
            </Field>
            <Field label="Target score (%)" error={check("targetScorePercent")}>
              {(props) => (
                <Input
                  {...props}
                  className="w-full sm:w-32"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={100}
                  value={draft.targetScorePercent ?? ""}
                  onChange={(event) => form.change({ targetScorePercent: wholeNumber(event.target.value, 100) })}
                />
              )}
            </Field>
            <Field label="Short-term goal" hint={`Up to ${GOAL_MAX} characters, kept on one line.`} error={check("shortTermGoal")}>
              {(props) => (
                <textarea
                  {...props}
                  rows={2}
                  maxLength={GOAL_MAX}
                  value={draft.shortTermGoal ?? ""}
                  onChange={(event) => form.change({ shortTermGoal: event.target.value })}
                  className="focus-field w-full rounded-xl border border-input bg-card px-3 py-2 text-sm sm:max-w-[28rem]"
                />
              )}
            </Field>
            <Field label="Long-term goal" hint={`Up to ${GOAL_MAX} characters, kept on one line.`} error={check("longTermGoal")}>
              {(props) => (
                <textarea
                  {...props}
                  rows={2}
                  maxLength={GOAL_MAX}
                  value={draft.longTermGoal ?? ""}
                  onChange={(event) => form.change({ longTermGoal: event.target.value })}
                  className="focus-field w-full rounded-xl border border-input bg-card px-3 py-2 text-sm sm:max-w-[28rem]"
                />
              )}
            </Field>
          </SettingsCard>

          <SettingsCard title="Topics">
            <TopicsEditor
              topics={draft.weakTopics ?? []}
              onChange={(weakTopics) => form.change({ weakTopics })}
              invalid={form.invalid("weakTopics")}
            />
          </SettingsCard>

          <SettingsCard
            title="Study time"
            description="Goals are measured in active time in PadhAI: minutes you're actually using the app, not all your studying."
            footer={<SaveFooter dirty={form.dirty} pending={form.pending} onCancel={form.reset} />}
          >
            <Field label="Daily goal (minutes)" error={check("dailyActiveMinutesGoal")}>
              {(props) => (
                <Input
                  {...props}
                  className="w-full sm:w-32"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={DAILY_MINUTES_MAX}
                  value={draft.dailyActiveMinutesGoal ?? ""}
                  onChange={(event) =>
                    form.change({ dailyActiveMinutesGoal: wholeNumber(event.target.value, DAILY_MINUTES_MAX) })
                  }
                />
              )}
            </Field>
            <Field label="Weekly goal (minutes)" error={check("weeklyActiveMinutesGoal")}>
              {(props) => (
                <Input
                  {...props}
                  className="w-full sm:w-32"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={WEEKLY_MINUTES_MAX}
                  value={draft.weeklyActiveMinutesGoal ?? ""}
                  onChange={(event) =>
                    form.change({ weeklyActiveMinutesGoal: wholeNumber(event.target.value, WEEKLY_MINUTES_MAX) })
                  }
                />
              )}
            </Field>
            <Field
              label="Preferred study time"
              hint="In your time zone. The daily reminder, if you turn it on, comes at this time."
              error={check("preferredStudyTime")}
            >
              {(props) => (
                <Input
                  {...props}
                  className="w-full sm:w-40"
                  type="time"
                  step={60}
                  value={draft.preferredStudyTime ?? ""}
                  onChange={(event) => form.change({ preferredStudyTime: event.target.value.slice(0, 5) || null })}
                />
              )}
            </Field>
          </SettingsCard>
        </form>
      )}
    </>
  );
}
