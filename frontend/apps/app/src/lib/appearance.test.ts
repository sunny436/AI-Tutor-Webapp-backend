import { describe, expect, test } from "bun:test";

import { APPEARANCE_CACHE_KEY, PREPAINT_SCRIPT, attributesFor } from "./appearance";

const neutral = { fontSize: "medium", highContrast: false, reduceMotion: false, readingComfort: false } as const;

describe("appearance attributes", () => {
  test("the defaults set nothing", () => {
    expect(attributesFor(neutral)).toEqual({
      "data-font-size": null,
      "data-contrast": null,
      "data-motion": null,
      "data-reading": null,
    });
  });

  test("each setting maps to its attribute", () => {
    expect(
      attributesFor({ fontSize: "x_large", highContrast: true, reduceMotion: true, readingComfort: true }),
    ).toEqual({
      "data-font-size": "x_large",
      "data-contrast": "high",
      "data-motion": "reduce",
      "data-reading": "comfort",
    });
  });
});

describe("the pre-paint script", () => {
  function run(stored: string | null) {
    const attributes: Record<string, string> = {};
    const context = {
      localStorage: { getItem: (key: string) => (key === APPEARANCE_CACHE_KEY ? stored : null) },
      document: {
        documentElement: {
          setAttribute: (name: string, value: string) => {
            attributes[name] = value;
          },
        },
      },
    };
    new Function("localStorage", "document", PREPAINT_SCRIPT)(context.localStorage, context.document);
    return attributes;
  }

  test("applies the cached attributes", () => {
    const cached = JSON.stringify({ "data-font-size": "large", "data-contrast": "high", "data-motion": null });
    expect(run(cached)).toEqual({ "data-font-size": "large", "data-contrast": "high" });
  });

  test("ignores nothing cached, broken JSON, unknown attributes and odd values", () => {
    expect(run(null)).toEqual({});
    expect(run("{not json")).toEqual({});
    expect(run(JSON.stringify({ onclick: "alert(1)", "data-font-size": "x\" onload=\"1" }))).toEqual({});
  });
});
