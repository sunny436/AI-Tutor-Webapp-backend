import { describe, expect, test } from "bun:test";
import { previewEnabled } from "./preview";

describe("previewEnabled", () => {
  test("is off unless the value is exactly 1", () => {
    for (const value of [undefined, "", "0", "true", "yes", " 1", "1 ", "on"]) {
      expect(previewEnabled(value)).toBe(false);
    }
    expect(previewEnabled("1")).toBe(true);
  });

  test("is off in an environment that does not set it", () => {
    const saved = process.env.PREVIEW_FEATURES;
    Reflect.deleteProperty(process.env, "PREVIEW_FEATURES");
    try {
      expect(previewEnabled()).toBe(false);
    } finally {
      if (saved !== undefined) process.env.PREVIEW_FEATURES = saved;
    }
  });
});
