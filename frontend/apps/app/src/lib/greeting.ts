/**
 * The study greeting above a new chat's composer: one of this week's pool from the API
 * (`GET /v1/greetings`, app-level, the same pool for everyone, refreshed weekly by the API), picked
 * at random for each new chat. The chat never depends on it: whatever goes wrong (no greeting live,
 * API down or slow, session gone), the pool is just FALLBACK and the server logs one line saying
 * why. Nothing is ever stored in the browser.
 */

import type { StudyGreetingPool } from "@/lib/api/types";
import type { BackendResult } from "@/lib/server/backend";

export const FALLBACK_GREETING = "What are you studying today?";
const MAX_LENGTH = 120;

/** Server-side: the greetings to pick from, or [FALLBACK] with one warning line. */
export function greetingPool(
  result: BackendResult<StudyGreetingPool>,
  warn: (line: string) => void = (line) => console.warn(line),
): string[] {
  const items = result.status === "ok" ? result.data?.items : undefined;
  const usable = Array.isArray(items)
    ? items.filter((text): text is string => typeof text === "string" && text.trim() !== "" && text.length <= MAX_LENGTH)
    : [];
  if (usable.length) return usable;
  const reason = result.status !== "ok" ? result.status : Array.isArray(items) && !items.length ? "empty" : "malformed";
  warn(`[greeting] ${reason}: showing the fallback`);
  return [FALLBACK_GREETING];
}

/**
 * A picker that gives each chat one greeting and keeps it (the same chat shows the same line when
 * the student comes back to it), and never gives a new chat the greeting the last one got.
 */
export function greetingPicker(random: () => number = Math.random) {
  const chosen = new Map<string, string>();
  let last: string | null = null;
  return (chatKey: string, pool: readonly string[]): string => {
    const kept = chosen.get(chatKey);
    if (kept !== undefined && pool.includes(kept)) return kept;
    const choices = pool.length > 1 ? pool.filter((text) => text !== last) : pool;
    const text = choices[Math.min(choices.length - 1, Math.floor(random() * choices.length))] ?? FALLBACK_GREETING;
    chosen.set(chatKey, text);
    last = text;
    return text;
  };
}

/** The page's picker: in memory only, for as long as the tab is open. */
export const pickGreeting = greetingPicker();
