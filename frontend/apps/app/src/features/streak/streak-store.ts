"use client";

import { useSyncExternalStore } from "react";

import { LEARNING_EVENT } from "@/lib/activity";
import { getStreak } from "@/lib/api/progress";
import type { LearningStreak } from "@/lib/api/types";

/**
 * The learning streak as the server reports it (GET /v1/progress/streak), shared by the header's
 * badge and countdown and by Settings > Learning & Streak: one request, never computed here.
 *
 * Fetched when first shown, again when a reply finishes (LEARNING_EVENT), when the tab comes
 * back (not within FRESH_MS of the last answer), and when the learning day ends. No polling. A
 * failed request keeps what was shown (or "error" when nothing was): the UI must never show a
 * streak of 0 it doesn't know.
 */

export type StreakState = { status: "loading" | "ready" | "error"; data: LearningStreak | null };

/** A tab shown again this soon after the last answer (switching tabs and back) asks nothing. */
const FRESH_MS = 15_000;
const LOADING: StreakState = { status: "loading", data: null };
let state: StreakState = LOADING;
let inflight: Promise<void> | null = null;
let fetchedAt = 0;
// Asked again while a request was on its way: its answer may predate what changed (a reply that
// just finished), so one more request follows it.
let again = false;
const listeners = new Set<() => void>();

function publish(next: StreakState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function refreshStreak(): Promise<void> {
  if (inflight) {
    again = true;
    return inflight;
  }
  inflight = getStreak()
    .then(
      (data) => {
        fetchedAt = Date.now();
        publish({ status: "ready", data });
      },
      () => publish(state.data ? state : { status: "error", data: null }),
    )
    .finally(() => {
      inflight = null;
      if (again) {
        again = false;
        void refreshStreak();
      }
    });
  return inflight;
}

const onLearning = () => void refreshStreak();
const onVisible = () => {
  if (document.visibilityState === "visible" && Date.now() - fetchedAt >= FRESH_MS) void refreshStreak();
};

function subscribe(listener: () => void): () => void {
  if (listeners.size === 0) {
    window.addEventListener(LEARNING_EVENT, onLearning);
    document.addEventListener("visibilitychange", onVisible);
    void refreshStreak();
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.removeEventListener(LEARNING_EVENT, onLearning);
      document.removeEventListener("visibilitychange", onVisible);
    }
  };
}

export function useStreak(): StreakState {
  return useSyncExternalStore(subscribe, () => state, () => LOADING);
}
