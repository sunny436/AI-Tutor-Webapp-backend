import { describe, expect, test } from "bun:test";

import { nextReveal } from "./smooth-text";

const WORDS = "The quick brown fox jumps over the lazy dog while plants make food from sunlight ".repeat(40);

describe("nextReveal", () => {
  test("shows only what arrived, and all of it when nothing more is coming", () => {
    expect(nextReveal("", 0)).toBe(0);
    expect(nextReveal("abc", 3)).toBe(3);
    expect(nextReveal("abc", 9)).toBe(3);
    expect(nextReveal("Hi", 0)).toBe(2);
  });

  test("a burst is caught up within a few ticks, in steps that shrink as it catches up", () => {
    const text = WORDS.slice(0, 1200);
    let shown = 0;
    const steps: number[] = [];
    while (shown < text.length) {
      const next = nextReveal(text, shown);
      expect(next).toBeGreaterThan(shown);
      expect(next).toBeLessThanOrEqual(text.length);
      steps.push(next - shown);
      shown = next;
    }
    expect(steps.length).toBeLessThanOrEqual(16); // 16 ticks of 50 ms: under a second for 1,200 characters
    expect(steps[0]).toBeGreaterThanOrEqual(400);
    expect(steps.slice(-3).every((step) => step <= 20)).toBe(true);
  });

  test("ends on a word when one is near, so words appear whole", () => {
    const text = "Photosynthesis happens in chloroplasts";
    const end = nextReveal(text, 0);
    expect([" ", undefined]).toContain(text[end]);
  });

  test("a steady stream is shown steadily, never far behind", () => {
    // One word every 50 ms (the E2E pace), revealed on the same 50 ms tick.
    const words = WORDS.split(/(?<= )/);
    let received = "";
    let shown = 0;
    const increments: number[] = [];
    let worstLag = 0;
    for (const word of words.slice(0, 200)) {
      received += word;
      const next = nextReveal(received, shown);
      increments.push(next - shown);
      shown = next;
      worstLag = Math.max(worstLag, received.length - shown);
    }
    const small = increments.filter((step) => step <= 120).length / increments.length;
    expect(small).toBeGreaterThanOrEqual(0.8);
    expect(worstLag).toBeLessThanOrEqual(24); // about three words: a few ticks, never seconds
  });
});
