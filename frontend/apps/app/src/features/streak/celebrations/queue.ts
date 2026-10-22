import type { LearningStreak, StreamLearning } from "@/lib/api/types";

/**
 * The streak celebrations' rules, kept pure so they can be tested without a page.
 *
 * What is celebrated comes only from the server: a finished reply's `done.learning` or a practice
 * answer's `learning` (sent once, by the answer that made its day a learning day;
 * app/progress/learning.py) and a confirmed lost streak (`currentStreak` 0 after a whole missed
 * India day, never while today is pending).
 */
export type Celebration =
  | { kind: StreamLearning["event"]; streak: number; key: string }
  | { kind: "lost"; previous: number; key: string };

export type QueueState = { items: Celebration[]; seen: ReadonlySet<string>; learned: boolean };

export const EMPTY_QUEUE: QueueState = { items: [], seen: new Set(), learned: false };

/** A finished reply's streak event: one per reply, keyed by its message. */
export function fromReply(learning: StreamLearning, messageId: string): Celebration {
  return { kind: learning.event, streak: learning.streak, key: `msg:${messageId}` };
}

/** A practice answer's streak event: keyed by the test's message and the answer, apart from the reply's own. */
export function fromAnswer(learning: StreamLearning, messageId: string, answered: number): Celebration {
  return { kind: learning.event, streak: learning.streak, key: `answer:${messageId}:${answered}` };
}

/** A confirmed lost streak, keyed per account and per lost streak; null when there is none. */
export function lostFor(userId: string, streak: LearningStreak): Celebration | null {
  if (streak.currentStreak !== 0 || streak.previousStreak <= 0 || !streak.lastLearningDate) return null;
  return { kind: "lost", previous: streak.previousStreak, key: `lost:${userId}:${streak.lastLearningDate}` };
}

/**
 * Offer one celebration; the first in `items` is the one shown, one at a time.
 * - A key seen before in this page is ignored: re-renders, Strict Mode, repeated responses.
 * - A learning event takes the place of a waiting or showing "lost" (the streak began again), and
 *   once one was seen, a "lost" is stale (today is a learning day, so the streak is not 0).
 */
export function offer(state: QueueState, item: Celebration): QueueState {
  if (state.seen.has(item.key) || (item.kind === "lost" && state.learned)) return state;
  const seen = new Set(state.seen).add(item.key);
  if (item.kind === "lost") return { ...state, seen, items: [...state.items, item] };
  return { seen, learned: true, items: [...state.items.filter((waiting) => waiting.kind !== "lost"), item] };
}

/** The celebration `key` ended (closed, timed out, or could not be shown): the next one may play. */
export function finish(state: QueueState, key: string): QueueState {
  return { ...state, items: state.items.filter((item) => item.key !== key) };
}
