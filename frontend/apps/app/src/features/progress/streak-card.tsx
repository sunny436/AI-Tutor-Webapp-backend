"use client";

import { Flame } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppearance } from "@/components/appearance-provider";
import { getProgress } from "@/lib/api/progress";
import { ACTIVITY_EVENT } from "@/lib/activity";

const REFRESH_AT_MOST_EVERY_MS = 60_000;

/**
 * The student's real streak (GET /v1/progress), in the sidebar. Hidden when they turned it off
 * (Settings > Progress & Goals), and while it cannot be read (no made-up number, ever).
 * Refreshes when a minute is credited or the tab comes back, at most once a minute.
 */
export function StreakCard({ onNavigate }: { onNavigate?: () => void }) {
  const appearance = useAppearance();
  const show = appearance?.appearance?.showStreak ?? false;
  const [days, setDays] = useState<number | null>(null);
  const last = useRef(0);

  const refresh = useCallback(async (force = false) => {
    if (!force && Date.now() - last.current < REFRESH_AT_MOST_EVERY_MS) return;
    last.current = Date.now();
    try {
      setDays((await getProgress(7)).streak.currentDays);
    } catch {
      // keep what is shown; the next refresh tries again
    }
  }, []);

  useEffect(() => {
    if (!show) return;
    void refresh(true);
    const onActivity = () => void refresh();
    const onVisible = () => document.visibilityState === "visible" && void refresh();
    window.addEventListener(ACTIVITY_EVENT, onActivity);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener(ACTIVITY_EVENT, onActivity);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [show, refresh]);

  if (!show || days === null) return null;
  return (
    <Link
      href="/settings/progress"
      onClick={onNavigate}
      className="focus-ring mx-4 mt-5 flex items-center gap-2 rounded-2xl border border-accent-warm/25 bg-gradient-to-r from-accent-warm-soft to-brand-soft p-3 transition-colors hover:border-accent-warm/40"
    >
      <span aria-hidden className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-streak text-white shadow-sm">
        <Flame className="h-4 w-4 fill-current" />
      </span>
      <span className="min-w-0">
        <span className="block whitespace-nowrap text-xs font-bold text-foreground">
          {days > 0 ? `${days}-day streak` : "No streak yet"}
        </span>
        <span className="block truncate text-2xs text-text-secondary">
          {days > 0 ? "Keep it going today" : "Use PadhAI today to start one"}
        </span>
      </span>
    </Link>
  );
}
