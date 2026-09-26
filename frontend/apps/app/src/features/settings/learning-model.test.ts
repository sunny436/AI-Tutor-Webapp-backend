import { describe, expect, test } from "bun:test";

import { CONTRACT } from "@/lib/api/contract.gen";
import { LEARNING_FIELDS, PREFERENCES, TUTOR_FIELDS } from "./learning-labels";
import { addSubject, addTopic, editFor, moveSubject, removeSubject, toggleSubject } from "./learning-model";

type Values = { grade: string; board: string; boardState: string; weakTopics: string[]; targetScorePercent: number };
type Loose = { [K in keyof Values]?: Values[K] | null | "" };

describe("editFor", () => {
  const fields = ["grade", "board", "boardState", "weakTopics", "targetScorePercent"] as const;
  const edit = (base: Loose, draft: Loose) => editFor<Loose>(base, draft, fields);

  test("only changed fields; a value is set, an emptied field is reset", () => {
    const base = { grade: "class_9", board: "state", boardState: "kerala", weakTopics: ["Optics"], targetScorePercent: 80 };
    const draft = { grade: "class_10", board: "cbse", boardState: "", weakTopics: [], targetScorePercent: 80 };
    expect(edit(base, draft)).toEqual({
      set: { grade: "class_10", board: "cbse" },
      reset: ["boardState", "weakTopics"],
    });
  });

  test("null, empty text and an empty list are all the same 'unset'", () => {
    expect(edit({ grade: null, weakTopics: [] }, { grade: "", weakTopics: [] })).toEqual({ set: {}, reset: [] });
  });

  test("zero is a value, not unset", () => {
    expect(edit({ targetScorePercent: null }, { targetScorePercent: 0 })).toEqual({
      set: { targetScorePercent: 0 },
      reset: [],
    });
  });
});

describe("weak topics", () => {
  const limits = { max: 3, maxLength: 10 };

  test("added clean, once, within the limits", () => {
    expect(addTopic([], "  Trig \n onometry ", { ...limits, maxLength: 60 })).toEqual({
      topics: ["Trig onometry"],
      error: null,
    });
    expect(addTopic(["Optics"], "optics", limits).error).toBe("That topic is already on the list.");
    expect(addTopic(["a", "b", "c"], "d", limits).error).toBe("You can list up to 3 topics.");
    expect(addTopic([], "x".repeat(11), limits).error).toBe("Keep a topic under 11 characters.");
    expect(addTopic(["a"], "   ", limits)).toEqual({ topics: ["a"], error: null });
  });
});

describe("the subject list", () => {
  const items = [
    { code: "mathematics", isPriority: false, needsImprovement: false },
    { code: "physics", isPriority: false, needsImprovement: false },
    { code: "chemistry", isPriority: false, needsImprovement: false },
  ];
  const codes = (list: typeof items) => list.map((item) => item.code);

  test("moves one place, and not past either end", () => {
    expect(codes(moveSubject(items, 2, -1))).toEqual(["mathematics", "chemistry", "physics"]);
    expect(codes(moveSubject(items, 0, -1))).toEqual(codes(items));
    expect(codes(moveSubject(items, 2, 1))).toEqual(codes(items));
  });

  test("adds once and within the limit; removes; flags one subject only", () => {
    expect(codes(addSubject(items, "biology", 15))).toEqual([...codes(items), "biology"]);
    expect(addSubject(items, "physics", 15)).toHaveLength(3);
    expect(addSubject(items, "biology", 3)).toHaveLength(3);
    expect(codes(removeSubject(items, "physics"))).toEqual(["mathematics", "chemistry"]);
    const flagged = toggleSubject(items, "physics", "isPriority");
    expect(flagged.map((item) => item.isPriority)).toEqual([false, true, false]);
  });
});

test("every preference is on exactly one page, and labelled for every value the API has", () => {
  const all = [...LEARNING_FIELDS, ...TUTOR_FIELDS];
  expect(new Set(all).size).toBe(all.length);
  expect(new Set<string>(all)).toEqual(new Set(Object.keys(CONTRACT.LearningPreferencesSet)));
  for (const field of all) {
    expect(Object.keys(PREFERENCES[field].options).sort()).toEqual([...CONTRACT.LearningPreferencesSet[field].enum].sort());
  }
});
