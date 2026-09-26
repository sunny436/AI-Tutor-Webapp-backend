import { expect, test } from "bun:test";

import { ACTIVE_WINDOW_MS, shouldReport } from "./activity";

const now = 1_000_000_000;

test("a minute counts only while visible and recently used, or while a reply streams", () => {
  expect(shouldReport({ visible: true, now, lastInteraction: now - 30_000, streaming: false })).toBe(true);
  expect(shouldReport({ visible: true, now, lastInteraction: now - ACTIVE_WINDOW_MS, streaming: false })).toBe(true);
  expect(shouldReport({ visible: true, now, lastInteraction: now - ACTIVE_WINDOW_MS - 1, streaming: false })).toBe(false);
  expect(shouldReport({ visible: true, now, lastInteraction: 0, streaming: true })).toBe(true);
  expect(shouldReport({ visible: false, now, lastInteraction: now, streaming: true })).toBe(false);
});
