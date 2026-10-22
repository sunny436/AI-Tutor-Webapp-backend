"use client";

import { Button } from "@v1/ui/button";
import { EmptyState, ErrorState } from "@v1/ui/empty-state";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { Timer } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";

import { ActivityChart } from "@/features/progress/activity-chart";
import { useCatalog } from "@/features/settings/learning-data";
import { ChoiceGroup } from "@/features/settings/primitives";
import { GoalBar } from "@/features/settings/progress-section";
import { describeError } from "@/lib/api/errors";
import { getProgress } from "@/lib/api/progress";
import { getStudySummary } from "@/lib/api/study";
import type { Progress, StudySummary } from "@/lib/api/types";
import { ACTIVITY_LABELS, formatStudyTime } from "./study-client";
import { StudySessionPanel } from "./study-session-panel";
import { useStudy } from "./study-store";

export const RANGES = [
  { value: "1", label: "Today" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
] as const;
type Range = (typeof RANGES)[number]["value"];

const link = "focus-ring rounded font-semibold text-brand underline underline-offset-2";

/** A titled card of the page (an `h2`; the app header owns the `h1`). Also used by My Learning. */
export function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="rounded-2xl border border-border bg-card p-4 elev-1 sm:p-5">
      <h2 id={id} className="mb-3 text-sm font-bold text-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** A number and what it is, inside a `<dl>`. Also used by My Learning. */
export function Stat({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div className="flex min-w-0 flex-col">
      <dt className="order-2 text-xs text-text-secondary">{label}</dt>
      <dd className="order-1 font-display text-2xl font-bold tabular-nums text-foreground">{value}</dd>
      {hint && <dd className="order-3 mt-1 text-2xs leading-relaxed text-text-secondary">{hint}</dd>}
    </div>
  );
}

/** Rows of name, bar and time; the bar only shows what the text says. */
function Breakdown({ rows, empty }: { rows: { key: string; label: string; seconds: number }[]; empty: string }) {
  if (!rows.length) return <p className="text-sm text-text-secondary">{empty}</p>;
  const top = Math.max(...rows.map((row) => row.seconds), 1);
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((row) => (
        <li key={row.key} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-foreground">{row.label}</span>
            <span className="shrink-0 tabular-nums text-text-secondary">{formatStudyTime(row.seconds)}</span>
          </div>
          <div aria-hidden className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max((row.seconds / top) * 100, 2)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

const STATUS_TEXT = {
  active: "In progress",
  paused: "Paused",
  ended: "Ended",
} as const;
const END_TEXT = { ended: "you ended it", stale: "no study activity", limit: "8-hour limit" } as const;

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

/** The day's goal is the existing active-time goal (Learning Goals), shown as it is measured. */
function DailyGoal() {
  const [progress, setProgress] = useState<Progress | null | "failed">(null);
  useEffect(() => {
    let cancelled = false;
    getProgress(7).then(
      (loaded) => !cancelled && setProgress(loaded),
      () => !cancelled && setProgress("failed"),
    );
    return () => {
      cancelled = true;
    };
  }, []);
  if (progress === null) return <Skeleton className="h-10 w-full rounded-xl" />;
  if (progress === "failed") return <p className="text-sm text-text-secondary">Your daily goal can't be loaded right now.</p>;
  const goal = progress.goals.dailyActiveMinutes;
  if (!goal) {
    return (
      <p className="text-sm text-text-secondary">
        You haven't set a daily goal.{" "}
        <Link href="/settings/goals" className={link}>
          Set one in Learning Goals
        </Link>
        .
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-text-secondary">
        Your goal is measured in active time in PadhAI (any use of the app), not study time: today {progress.today.activeMinutes}{" "}
        min.
      </p>
      <GoalBar done={progress.today.activeMinutes} goal={goal} label="Today's goal" />
    </div>
  );
}

/** The summary's states: loading, error (with retry), nothing recorded yet, and the numbers. */
export function StudySummaryContent({
  summary: shown,
  error,
  days,
  subjectName,
  onRetry,
}: {
  summary: StudySummary | null;
  error: unknown;
  days: number;
  subjectName: (code: string | null) => string;
  onRetry: () => void;
}) {
  if (error) {
    return (
      <ErrorState
        title="Couldn't load your study activity"
        description={describeError(error).message}
        action={
          <Button variant="outline" onClick={onRetry}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!shown) {
    return (
      <SkeletonGroup label="Loading your study activity" className="space-y-3">
        <Skeleton className="h-28 w-full rounded-2xl" />
        <Skeleton className="h-56 w-full rounded-2xl" />
      </SkeletonGroup>
    );
  }
  if (!shown.firstRecordedDate) {
    return (
      <EmptyState
        icon={Timer}
        title="Nothing recorded yet"
        description="Start a study session from the tutor or your files: your estimated study time will show here."
        action={null}
      />
    );
  }
  return (
    <>
      <Panel id="study-totals" title={days === 1 ? "Today" : `Last ${days} days`}>
        <dl className="grid gap-5 sm:grid-cols-2">
          <Stat
            value={formatStudyTime(shown.totals.activeSeconds)}
            label="estimated study time"
            hint="Active learning in your study sessions."
          />
          <Stat
            value={formatStudyTime(shown.totals.appSeconds)}
            label="time in PadhAI"
            hint="Any time PadhAI was open, studying or not."
          />
        </dl>
        <dl className="mt-5 grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-3">
          <Stat
            value={formatStudyTime(shown.totals.activeSeconds)}
            label="active"
            hint="In a running session, on the tutor or your files, page on screen, and you were active."
          />
          <Stat
            value={formatStudyTime(shown.totals.idleSeconds)}
            label="idle"
            hint="In a running session, but no activity was seen, the page was hidden, or you were elsewhere."
          />
          <Stat value={formatStudyTime(shown.totals.pausedSeconds)} label="paused" hint="Time you paused a session." />
        </dl>
        {shown.firstRecordedDate > shown.from && (
          <p className="mt-4 text-2xs text-text-secondary">
            Study time has been recorded since {new Date(`${shown.firstRecordedDate}T00:00:00`).toLocaleDateString()}: earlier
            days have no data.
          </p>
        )}
      </Panel>

      <Panel id="study-goal" title="Daily goal">
        <DailyGoal />
      </Panel>

      {shown.days.length > 1 && (
        <Panel id="study-trend" title="Trend">
          <ActivityChart
            days={shown.days.map((day) => ({ date: day.date, activeMinutes: Math.floor(day.activeSeconds / 60) }))}
            goal={null}
            title={`Estimated study minutes, last ${shown.days.length} days`}
            valueLabel="of estimated study"
            columnLabel="Study time"
          />
        </Panel>
      )}

      <div className="grid gap-5 md:grid-cols-2">
        <Panel id="study-subjects" title="By subject">
          <Breakdown
            rows={shown.subjects.map((row) => ({
              key: row.subject ?? "none",
              label: subjectName(row.subject),
              seconds: row.activeSeconds,
            }))}
            empty="No study time in this range."
          />
        </Panel>
        <Panel id="study-activities" title="By activity">
          <Breakdown
            rows={shown.activities.map((row) => ({
              key: row.activity,
              label: ACTIVITY_LABELS[row.activity],
              seconds: row.activeSeconds,
            }))}
            empty="No study time in this range."
          />
        </Panel>
      </div>

      <Panel id="study-chapters" title="By chapter">
        <Breakdown
          rows={shown.chapters.map((row) => ({
            key: row.chapterId,
            label: `${row.chapterTitle}${row.subject ? ` (${subjectName(row.subject)})` : ""}`,
            seconds: row.activeSeconds,
          }))}
          empty="No chapter was chosen for study time in this range."
        />
      </Panel>

      <Panel id="study-sessions" title="Recent sessions">
        {shown.sessions.length ? (
          <ul className="divide-y divide-border">
            {shown.sessions.map((session) => (
              <li key={session.id} className="flex flex-col gap-0.5 py-2.5 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
                  <span className="font-semibold text-foreground">{when(session.startedAt)}</span>
                  <span className="tabular-nums text-text-secondary">
                    {formatStudyTime(session.activeSeconds)} study · {formatStudyTime(session.durationSeconds)} long
                  </span>
                </div>
                <p className="text-xs text-text-secondary">
                  {STATUS_TEXT[session.status]}
                  {session.status === "ended" && session.endReason ? ` (${END_TEXT[session.endReason]})` : ""}
                  {" · "}
                  {[...session.subjects.map(subjectName), ...session.chapters].join(", ")}
                  {" · "}
                  {session.activities.map((activity) => ACTIVITY_LABELS[activity]).join(", ")}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-text-secondary">No study sessions in this range.</p>
        )}
      </Panel>
    </>

  );
}

/**
 * Study Activity: the student's own estimated study time, from the server only (GET
 * /v1/study/summary): today or recent days, active / idle / paused, by subject, chapter and
 * activity, recent sessions and the daily trend. Days with nothing recorded before tracking began
 * are left out, not shown as zero.
 */
export function StudyActivityView() {
  const [range, setRange] = useState<Range>("7");
  const [summary, setSummary] = useState<StudySummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const study = useStudy();
  const { catalog } = useCatalog();
  // Reload when the session starts, pauses, resumes or ends (here or on another tab or device).
  const sessionKey = `${study.server?.session?.id ?? "none"}:${study.server?.session?.status ?? ""}`;

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getStudySummary(Number(range), controller.signal).then(
      (loaded) => setSummary(loaded),
      (failure) => !controller.signal.aborted && setError(failure),
    );
    return () => controller.abort();
  }, [range, sessionKey, attempt]);

  const subjectName = (code: string | null) =>
    code ? (catalog?.subjects.find((entry) => entry.code === code)?.name ?? code) : "No subject chosen";

  return (
    <div
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard-focusable to be scrollable
      tabIndex={0}
      role="region"
      aria-label="Study Activity"
      className="scrollbar-subtle focus-ring-inset h-full overflow-y-auto"
    >
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6">
        <Panel id="study-session" title="Current session">
          <StudySessionPanel />
        </Panel>

        <ChoiceGroup
          legend="Show"
          value={range}
          options={RANGES}
          onChange={(value) => {
            setSummary(null);
            setRange(value);
          }}
        />

        <StudySummaryContent
          summary={summary}
          error={error}
          days={Number(range)}
          subjectName={subjectName}
          onRetry={() => setAttempt((count) => count + 1)}
        />

        <p className="text-xs leading-relaxed text-text-secondary">
          Study time is an estimate of learning activity, not proof of attention or understanding, and only you can see it.{" "}
          <Link href="/settings/study-tracking" className={link}>
            How it's measured
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
