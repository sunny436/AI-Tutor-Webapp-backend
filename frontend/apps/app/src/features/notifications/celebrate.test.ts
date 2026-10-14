import { describe, expect, test } from "bun:test";

import { unreadBadge } from "./celebrate";

describe("the bell", () => {
  test("the unread badge", () => {
    expect(unreadBadge(0)).toBeNull();
    expect(unreadBadge(3)).toBe("3");
    expect(unreadBadge(10)).toBe("9+");
  });
});
