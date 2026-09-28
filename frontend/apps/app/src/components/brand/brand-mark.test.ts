import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { BRAND } from "@/lib/brand";

/** The logo (also the favicon) changes colour with the palette; its shape never changes. */
const SVG = readFileSync(join(import.meta.dir, "..", "..", "..", "public", BRAND.markSrc), "utf-8");

describe("the brand mark", () => {
  test("keeps its geometry, size and name", () => {
    for (const part of [
      'viewBox="0 0 32 32"',
      'role="img" aria-label="PadhAI"',
      'x1="0" y1="32" x2="32" y2="0"',
      '<rect width="32" height="32" rx="9" fill="url(#padhai-mark-fill)"/>',
      'transform="translate(6.4 6.9) scale(0.8)" fill="none" stroke="#FFFFFF" stroke-width="2.1"',
      'd="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"',
      'd="M22 10v6"',
      'd="M6 12.5V16a6 3 0 0 0 12 0v-3.5"',
    ]) {
      expect(SVG).toContain(part);
    }
  });

  test("is drawn in the slate blue, one gradient, no violet", () => {
    expect([...SVG.matchAll(/stop-color="(#[0-9A-F]{6})"/gi)].map((match) => match[1])).toEqual(["#4F6F8F", "#6B8CAB"]);
    expect(SVG).not.toMatch(/#(4F46E5|7C3AED)/i);
  });
});
