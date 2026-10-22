"use client";

import { cn } from "@v1/ui/utils";
import { Flame, Hourglass } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAppearance } from "@/components/appearance-provider";
import { dayHasEnded, describeRemaining } from "./countdown";
import { refreshStreak, type StreakState, useStreak } from "./streak-store";

const pill =
  "focus-ring inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-sm font-semibold tabular-nums text-foreground sm:px-3";

export function streakBadgeVisible(appearance: ReturnType<typeof useAppearance>): boolean {
  return !(appearance?.appearance && !appearance.appearance.showStreak);
}

export function dayCountdownVisible(streak: StreakState): boolean {
  return Boolean(streak.data?.dayEnd);
}

/**
 * 🔥 N in the header: the server's learning streak, a link to Settings > Learning & Streak.
 * Muted while today is still pending; "–" (not 0) while it can't be read. Hidden when the
 * student turned it off (Appearance: "Show my streak in the header").
 */
export function StreakBadge() {
  const { status, data } = useStreak();
  const appearance = useAppearance();
  const known = status === "ready" && data;
  // A new number rises in; the first one the page shows simply appears.
  const shown = known ? data.currentStreak : null;
  const first = useRef<number | null>(null);
  if (first.current === null && shown !== null) first.current = shown;
  const rise = shown !== null && shown !== first.current;
  if (!streakBadgeVisible(appearance)) return null;
  const label = known
    ? `${data.currentStreak} day learning streak${data.todayActive ? "" : ", today's learning still to do"}`
    : "Learning streak unavailable";
  return (
    <Link href="/settings/streak" aria-label={label} title={label} className={cn(pill, "hover:bg-surface-2")}>
      <Flame
        aria-hidden
        className={cn("h-4 w-4 transition-colors", known && data.todayActive ? "fill-current text-streak" : "text-text-secondary")}
      />
      <span key={shown ?? "unknown"} aria-hidden className={cn("inline-block", rise && "animate-rise-in")}>
        {known ? data.currentStreak : "–"}
      </span>
    </Link>
  );
}

/**
 * ⏳ the time left in today's learning day (India midnight, from the server's `dayEnd`). The
 * only timer of the streak system: one interval here, cleared on unmount; at the end of the
 * day the streak is asked for again (the new day's end comes with it).
 */
export function DayCountdown({ className }: { className?: string }) {
  const { status, data } = useStreak();
  const dayEnd = data?.dayEnd;
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (!dayEnd) return;
    setNow(Date.now());
    let asked = false;
    const timer = window.setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (!asked && dayHasEnded(dayEnd, current)) {
        asked = true;
        void refreshStreak();
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [dayEnd]);

  if (!dayEnd || now === null) {
    // Hold the pill's place while the streak loads, so the header does not shift when it arrives.
    return status === "loading" || dayEnd ? (
      <span aria-hidden className={cn(pill, "invisible font-medium", className)}>
        <Hourglass className="h-4 w-4" />
        00h 00m
      </span>
    ) : null;
  }
  const { short, spoken } = describeRemaining(Date.parse(dayEnd) - now);
  return (
    <span className={cn(pill, "font-medium text-text-secondary", className)} title={spoken}>
      <Hourglass aria-hidden className="h-4 w-4" />
      <span aria-hidden>{short}</span>
      <span className="sr-only">{spoken}</span>
    </span>
  );
}
