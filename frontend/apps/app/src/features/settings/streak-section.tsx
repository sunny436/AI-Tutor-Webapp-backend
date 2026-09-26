"use client";

import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { CheckCircle2, Circle, Flame } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";

import { useAppearance } from "@/components/appearance-provider";
import { useStreak } from "@/features/streak/streak-store";
import { LEARNING_EVENT } from "@/lib/activity";
import { describeError } from "@/lib/api/errors";
import { getLearningDays } from "@/lib/api/progress";
import type { LearningDays } from "@/lib/api/types";
import { SectionHeading, SettingsCard, ToggleRow } from "./primitives";

// d3 and the calendar load on this page only, not with the rest of the app.
const LearningActivityCalendar = dynamic(
  () => import("@/features/streak/LearningActivityCalendar").then((module) => module.LearningActivityCalendar),
  { ssr: false, loading: () => <Skeleton className="h-40 w-full rounded-xl" /> },
);

function longDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year as number, (month as number) - 1, day as number).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function daysLabel(n: number): string {
  return `${n} ${n === 1 ? "day" : "days"}`;
}

/** Settings > Learning & Streak: the streak, today's learning, and the year's calendar. */
export function StreakSection() {
  const appearance = useAppearance();
  const streak = useStreak();
  const [calendar, setCalendar] = useState<LearningDays | null>(null);
  const [calendarError, setCalendarError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const loadCalendar = useCallback(() => {
    setCalendarError(null);
    getLearningDays().then(setCalendar, setCalendarError);
  }, []);

  useEffect(() => {
    loadCalendar();
    window.addEventListener(LEARNING_EVENT, loadCalendar);
    return () => window.removeEventListener(LEARNING_EVENT, loadCalendar);
  }, [loadCalendar]);

  const data = streak.data;
  const selectedDay = selected ? calendar?.days.find((day) => day.date === selected) : null;

  return (
    <>
      <SectionHeading
        title="Learning & Streak"
        description="Your streak counts the days you learnt with your tutor: a real question, fully answered. Days follow India time."
      />
      <div className="flex flex-col gap-4">
        {streak.status === "loading" ? (
          <SkeletonGroup label="Loading your streak">
            <Skeleton className="h-36 w-full rounded-2xl" />
          </SkeletonGroup>
        ) : !data ? (
          <SettingsCard title="Couldn't load your streak">
            <p className="text-sm text-text-secondary">Your streak is safe; it just can't be shown right now.</p>
          </SettingsCard>
        ) : (
          <SettingsCard title="Your streak">
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div className="flex flex-col-reverse">
                <dt className="text-xs text-text-secondary">Current streak</dt>
                <dd className="flex items-center gap-1.5 text-2xl font-bold tabular-nums text-foreground">
                  <Flame aria-hidden className={data.todayActive ? "h-5 w-5 fill-current text-streak" : "h-5 w-5 text-text-secondary"} />
                  {daysLabel(data.currentStreak)}
                </dd>
              </div>
              <div className="flex flex-col-reverse">
                <dt className="text-xs text-text-secondary">Longest streak</dt>
                <dd className="text-2xl font-bold tabular-nums text-foreground">{daysLabel(data.longestStreak)}</dd>
              </div>
              <div className="col-span-2 flex flex-col-reverse sm:col-span-1">
                <dt className="text-xs text-text-secondary">Today's learning</dt>
                <dd className="flex items-center gap-1.5 text-base font-semibold text-foreground">
                  {data.todayActive ? (
                    <>
                      <CheckCircle2 aria-hidden className="h-5 w-5 text-success" /> Completed
                    </>
                  ) : (
                    <>
                      <Circle aria-hidden className="h-5 w-5 text-text-secondary" /> Not completed
                    </>
                  )}
                </dd>
              </div>
            </dl>
            <p className="text-sm text-text-secondary">
              {data.todayActive
                ? "Today counts. Come back tomorrow to keep it going."
                : data.currentStreak
                  ? "Ask your tutor a real question today to keep your streak going."
                  : "Ask your tutor a real question to start a streak."}{" "}
              Greetings like "hi" and unanswered questions don't count.
            </p>
          </SettingsCard>
        )}

        <SettingsCard title="Activity" description="Each square is a day; the darker, the more you learnt.">
          {calendarError ? (
            <div className="flex flex-col items-start gap-2">
              <p className="text-sm text-text-secondary">{describeError(calendarError).message}</p>
              <button
                type="button"
                onClick={loadCalendar}
                className="focus-ring rounded text-sm font-medium text-brand underline underline-offset-2"
              >
                Try again
              </button>
            </div>
          ) : !calendar ? (
            <SkeletonGroup label="Loading your calendar">
              <Skeleton className="h-40 w-full rounded-xl" />
            </SkeletonGroup>
          ) : (
            <>
              <div className="max-w-full overflow-x-clip">
                <LearningActivityCalendar days={calendar.days} start={calendar.start} onSelect={setSelected} />
              </div>
              <div aria-live="polite" className="min-h-[3.5rem] rounded-xl bg-surface px-4 py-3 text-sm">
                {selected ? (
                  <>
                    <p className="font-semibold text-foreground">{longDate(selected)}</p>
                    <p className="text-text-secondary">
                      {selectedDay
                        ? `✓ Learning day · ${selectedDay.interactions} learning interaction${selectedDay.interactions === 1 ? "" : "s"}`
                        : "No learning that day"}
                    </p>
                  </>
                ) : (
                  <p className="text-text-secondary">Choose a day to see what you did.</p>
                )}
              </div>
            </>
          )}
        </SettingsCard>

        {appearance?.appearance && (
          <SettingsCard title="In the header">
            <ToggleRow
              label="Show my streak in the header"
              description="The 🔥 next to the time left today. Your streak counts either way."
              checked={appearance.appearance.showStreak}
              onCheckedChange={(showStreak) => appearance.change({ showStreak })}
            />
          </SettingsCard>
        )}
      </div>
    </>
  );
}
