import { describe, expect, test } from "bun:test";

import type { LearningStreak } from "@/lib/api/types";
import { type Celebration, EMPTY_QUEUE, finish, fromReply, lostFor, offer } from "./queue";

const streak = (currentStreak: number, previousStreak: number, lastLearningDate: string | null): LearningStreak => ({
  currentStreak,
  longestStreak: Math.max(currentStreak, previousStreak),
  todayActive: currentStreak > 0,
  todayDate: "2026-10-14",
  timezone: "Asia/Kolkata",
  dayEnd: "2026-10-14T18:30:00Z",
  previousStreak,
  lastLearningDate,
});
const shown = (items: Celebration[]) => items.map((item) => item.key);

describe("streak celebrations", () => {
  test("each event plays once, one at a time; a new start replaces a lost streak; stale losses are ignored", () => {
    const lost = lostFor("u1", streak(0, 5, "2026-10-11"));
    expect(lost).toEqual({ kind: "lost", previous: 5, key: "lost:u1:2026-10-11" });
    // Only a confirmed loss: not a pending day, not a student who never learnt.
    expect(lostFor("u1", streak(5, 0, "2026-10-13"))).toBeNull();
    expect(lostFor("u1", streak(0, 0, null))).toBeNull();
    // Per account: another student in the same browser has their own key.
    expect(lostFor("u2", streak(0, 5, "2026-10-11"))?.key).toBe("lost:u2:2026-10-11");

    let state = offer(EMPTY_QUEUE, lost as Celebration);
    state = offer(state, lost as Celebration); // a repeated response, a re-render, Strict Mode
    expect(shown(state.items)).toEqual(["lost:u1:2026-10-11"]);

    const started = fromReply({ event: "started", streak: 1 }, "m1");
    state = offer(state, started);
    expect(shown(state.items)).toEqual(["msg:m1"]); // the new streak takes the loss's place
    state = offer(state, started);
    expect(shown(state.items)).toEqual(["msg:m1"]);
    // A late, stale answer still saying "lost" after today became a learning day: ignored.
    state = offer(state, lostFor("u1", streak(0, 5, "2026-10-12")) as Celebration);
    expect(shown(state.items)).toEqual(["msg:m1"]);

    state = finish(state, "msg:m1");
    expect(state.items).toEqual([]);
    state = offer(state, started); // a finished celebration never comes back
    expect(state.items).toEqual([]);
    state = offer(state, fromReply({ event: "milestone", streak: 7 }, "m2"));
    expect(state.items).toEqual([{ kind: "milestone", streak: 7, key: "msg:m2" }]);
  });
});
