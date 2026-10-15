"use client";

import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ActivityChart } from "@/features/progress/activity-chart";
import { ACTIVITY_EVENT } from "@/lib/activity";
import { describeError } from "@/lib/api/errors";
import { getProgress } from "@/lib/api/progress";
import type { Progress } from "@/lib/api/types";
import { Notice, SectionHeading, SettingsCard } from "./primitives";

function about(value: number): string {
  return value === 0 ? "0 min" : `about ${value} min`;
}

export function GoalBar({ done, goal, label }: { done: number; goal: number; label: string }) {
  const percent = Math.min(Math.round((done / goal) * 100), 100);
  return (
    <div className="flex flex-col gap-1">
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={goal}
        aria-valuenow={Math.min(done, goal)}
        aria-valuetext={`${done} of ${goal} minutes`}
        className="h-2 w-full overflow-hidden rounded-full bg-surface-2"
      >
        <div className="h-full rounded-full bg-brand" style={{ width: `${percent}%` }} />
      </div>
      <p className="text-xs text-text-secondary">
        {done >= goal ? "Goal reached." : `${goal - done} min to go.`} Goal: {goal} min.
      </p>
    </div>
  );
}

/** A number under its label: read label first ("current streak, 3 days"), shown number first. */
function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex min-w-0 flex-col-reverse">
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className="font-display text-2xl font-bold tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

export function ProgressSection() {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  // One fetch per attempt, and again whenever a minute is credited while the page is open.
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getProgress(14).then(
        (loaded) => {
          if (cancelled) return;
          setProgress(loaded);
          setError(null);
        },
        (failure) => {
          if (!cancelled) setError(failure);
        },
      );
    void load();
    window.addEventListener(ACTIVITY_EVENT, load);
    return () => {
      cancelled = true;
      window.removeEventListener(ACTIVITY_EVENT, load);
    };
  }, [attempt]);

  return (
    <>
      <SectionHeading
        title="Progress & Goals"
        description="Your active time in PadhAI and the questions you've asked, measured from how you use the app."
      />
      {error ? (
        <SettingsCard title="Couldn't load your progress">
          <p className="text-sm text-text-secondary">{describeError(error).message}</p>
          <button
            type="button"
            onClick={() => setAttempt((count) => count + 1)}
            className="focus-ring self-start rounded text-sm font-medium text-brand underline underline-offset-2"
          >
            Try again
          </button>
        </SettingsCard>
      ) : !progress ? (
        <SkeletonGroup label="Loading your progress" className="space-y-3">
          <Skeleton className="h-32 w-full rounded-2xl" />
          <Skeleton className="h-56 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <div className="flex flex-col gap-4">
          {progress.timezoneIsDefault && (
            <Notice>
              Your days follow {progress.timezone.replaceAll("_", " ")} time until you{" "}
              <Link href="/settings/profile" className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
                set your time zone
              </Link>
              .
            </Notice>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <SettingsCard title="Today">
              <dl className="flex gap-8">
                <Stat value={about(progress.today.activeMinutes)} label="active time" />
                <Stat value={String(progress.today.questions)} label={progress.today.questions === 1 ? "question" : "questions"} />
              </dl>
              {progress.goals.dailyActiveMinutes ? (
                <GoalBar done={progress.today.activeMinutes} goal={progress.goals.dailyActiveMinutes} label="Today's goal" />
              ) : null}
            </SettingsCard>
            <SettingsCard title="This week">
              <dl className="flex gap-8">
                <Stat value={about(progress.thisWeek.activeMinutes)} label="active time" />
                <Stat
                  value={String(progress.thisWeek.questions)}
                  label={progress.thisWeek.questions === 1 ? "question" : "questions"}
                />
              </dl>
              {progress.goals.weeklyActiveMinutes ? (
                <GoalBar done={progress.thisWeek.activeMinutes} goal={progress.goals.weeklyActiveMinutes} label="This week's goal" />
              ) : null}
            </SettingsCard>
          </div>
          {!progress.goals.dailyActiveMinutes && !progress.goals.weeklyActiveMinutes && (
            <p className="text-sm text-text-secondary">
              Set daily or weekly goals in{" "}
              <Link href="/settings/goals" className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
                Learning Goals
              </Link>
              .
            </p>
          )}
          <p className="text-sm text-text-secondary">
            Your estimated study time, from the study sessions you start, is in{" "}
            <Link href="/study" className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
              Study Activity
            </Link>
            .
          </p>
          <p className="text-sm text-text-secondary">
            Your learning streak and calendar are in{" "}
            <Link href="/settings/streak" className="focus-ring rounded font-semibold text-brand underline underline-offset-2">
              Learning &amp; Streak
            </Link>
            .
          </p>
          <SettingsCard title="Recent days">
            <ActivityChart days={progress.days} goal={progress.goals.dailyActiveMinutes} />
          </SettingsCard>
          <SettingsCard title="How active time is measured">
            <p className="text-sm leading-relaxed text-text-secondary">
              A minute counts when PadhAI is open and on screen, and you used it (typed, clicked, scrolled) or a reply
              was being written, within the last two minutes. At most one minute is counted per minute, however many
              tabs or devices you use. It's how much you used the app, not all of your studying, and it's never
              compared with anyone else's.
            </p>
          </SettingsCard>
        </div>
      )}
    </>
  );
}
