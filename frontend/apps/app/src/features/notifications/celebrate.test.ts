import { describe, expect, test } from "bun:test";

import type { AppNotification } from "@/lib/api/types";
import { milestonesToCelebrate, unreadBadge } from "./celebrate";

const item = (id: string, kind: string, readAt: string | null = null): AppNotification => ({
  id,
  kind,
  title: id,
  body: "",
  link: null,
  createdAt: "2026-09-26T10:00:00Z",
  readAt,
});

describe("the bell", () => {
  test("celebrates each unread milestone once, oldest first", () => {
    const items = [item("m7", "streak_milestone"), item("r", "streak_reminder"), item("m3", "streak_milestone")];
    expect(milestonesToCelebrate(items, new Set()).map((n) => n.id)).toEqual(["m3", "m7"]);
    expect(milestonesToCelebrate(items, new Set(["m3"])).map((n) => n.id)).toEqual(["m7"]);
    expect(milestonesToCelebrate([item("m", "streak_milestone", "2026-09-26T11:00:00Z")], new Set())).toEqual([]);
  });

  test("the unread badge", () => {
    expect(unreadBadge(0)).toBeNull();
    expect(unreadBadge(3)).toBe("3");
    expect(unreadBadge(10)).toBe("9+");
  });
});
