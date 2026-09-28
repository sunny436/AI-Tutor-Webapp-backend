import { describe, expect, test } from "bun:test";

import { FALLBACK_GREETING, greetingPicker, greetingPool } from "./greeting";

const POOL = ["Ready to learn something new?", "What's puzzling you today?", "Let's solve this together."];

describe("greetingPool", () => {
  test("this week's pool from the API, silently", () => {
    const lines: string[] = [];
    expect(greetingPool({ status: "ok", data: { weekOf: "2026-09-28", items: POOL } }, (l) => lines.push(l))).toEqual(POOL);
    expect(lines).toEqual([]);
  });

  for (const status of ["not_found", "unavailable", "unauthorized"] as const) {
    test(`${status}: the fallback, and one warning`, () => {
      const lines: string[] = [];
      expect(greetingPool({ status }, (l) => lines.push(l))).toEqual([FALLBACK_GREETING]);
      expect(lines).toEqual([`[greeting] ${status}: showing the fallback`]);
    });
  }

  test("an empty pool: the fallback, and one warning", () => {
    const lines: string[] = [];
    expect(greetingPool({ status: "ok", data: { weekOf: "2026-09-28", items: [] } }, (l) => lines.push(l))).toEqual([
      FALLBACK_GREETING,
    ]);
    expect(lines).toEqual(["[greeting] empty: showing the fallback"]);
  });

  test("a malformed answer keeps only usable lines, or falls back", () => {
    const lines: string[] = [];
    const mixed = { weekOf: "", items: ["  ", 7, "x".repeat(121), "Let's solve this together."] as unknown as string[] };
    expect(greetingPool({ status: "ok", data: mixed }, (l) => lines.push(l))).toEqual(["Let's solve this together."]);
    const broken = { weekOf: "", items: "nope" as unknown as string[] };
    expect(greetingPool({ status: "ok", data: broken }, (l) => lines.push(l))).toEqual([FALLBACK_GREETING]);
    expect(lines).toEqual(["[greeting] malformed: showing the fallback"]);
  });
});

describe("greetingPicker", () => {
  test("random across the pool, never the previous chat's greeting twice running", () => {
    let seed = 7;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    };
    const pick = greetingPicker(random);
    const picks = Array.from({ length: 300 }, (_, n) => pick(`chat-${n}`, POOL));
    for (let n = 1; n < picks.length; n++) expect(picks[n]).not.toBe(picks[n - 1]);
    expect(new Set(picks)).toEqual(new Set(POOL));
  });

  test("the same chat keeps its greeting", () => {
    const pick = greetingPicker(() => 0.99);
    const first = pick("draft-1", POOL);
    expect(pick("draft-2", POOL)).not.toBe(first);
    expect(pick("draft-1", POOL)).toBe(first);
  });

  test("one greeting, or none, never fails", () => {
    const pick = greetingPicker(() => 0.5);
    expect(pick("a", ["Only one."])).toBe("Only one.");
    expect(pick("b", ["Only one."])).toBe("Only one.");
    expect(pick("c", [])).toBe(FALLBACK_GREETING);
    expect(greetingPicker(() => 1)("d", POOL)).toBe("Let's solve this together."); // random() at its top edge stays in range
  });
});
