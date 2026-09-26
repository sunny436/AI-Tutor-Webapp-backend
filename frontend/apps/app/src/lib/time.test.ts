import { expect, test } from "bun:test";

import { relativeTime } from "./time";

const now = new Date("2026-09-26T12:00:00Z");
const ago = (seconds: number) => new Date(now.getTime() - seconds * 1000).toISOString();

test("relative times read naturally", () => {
  expect(relativeTime(ago(10), now)).toBe("just now");
  expect(relativeTime(ago(5 * 60), now)).toBe("5 minutes ago");
  expect(relativeTime(ago(2 * 3600), now)).toBe("2 hours ago");
  expect(relativeTime(ago(86_400), now)).toBe("yesterday");
  expect(relativeTime(ago(3 * 86_400), now)).toBe("3 days ago");
  expect(relativeTime(ago(21 * 86_400), now)).toBe("3 weeks ago");
  expect(relativeTime("not a date", now)).toBe("");
});
