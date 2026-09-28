import { describe, expect, test } from "bun:test";

import { FALLBACK_GREETING, greetingText } from "./greeting";

describe("greetingText", () => {
  test("this week's greeting from the API, silently", () => {
    const lines: string[] = [];
    const text = greetingText({ status: "ok", data: { text: "Let's solve this together.", weekOf: "2026-09-28" } }, (l) =>
      lines.push(l),
    );
    expect(text).toBe("Let's solve this together.");
    expect(lines).toEqual([]);
  });

  for (const status of ["not_found", "unavailable", "unauthorized"] as const) {
    test(`${status}: the fallback, and one warning`, () => {
      const lines: string[] = [];
      expect(greetingText({ status }, (l) => lines.push(l))).toBe(FALLBACK_GREETING);
      expect(lines).toEqual([`[greeting] ${status}: showing the fallback`]);
    });
  }

  test("a malformed answer: the fallback, and one warning", () => {
    const lines: string[] = [];
    expect(greetingText({ status: "ok", data: { text: "  ", weekOf: "" } }, (l) => lines.push(l))).toBe(FALLBACK_GREETING);
    expect(lines).toEqual(["[greeting] malformed: showing the fallback"]);
  });
});
