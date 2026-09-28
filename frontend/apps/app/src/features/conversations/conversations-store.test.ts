import { describe, expect, test } from "bun:test";
import { ApiError } from "@/lib/api/errors";
import type { Conversation, ConversationPage } from "@/lib/api/types";
import { type ConversationsApi, ConversationsStore, PAGE_SIZE } from "./conversations-store";

const convo = (n: number, updated: string, title = `Chat ${n}`): Conversation => ({
  id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  title,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: updated,
});

function fakeApi(pages: Record<string, ConversationPage>, options: { failRename?: boolean } = {}) {
  const calls: string[] = [];
  const api: ConversationsApi = {
    listConversations: async ({ cursor }) => {
      calls.push(`list:${cursor ?? ""}`);
      const page = pages[cursor ?? ""];
      if (!page) throw new ApiError(503, "service_unavailable");
      return page;
    },
    renameConversation: async (id, title) => {
      calls.push(`rename:${title}`);
      if (options.failRename) throw new ApiError(422, "validation_error");
      return { ...convo(0, "2026-02-01T00:00:00Z"), id, title };
    },
  };
  return { api, calls };
}

describe("ConversationsStore", () => {
  test("starts from the server-rendered first page without fetching", () => {
    const { api, calls } = fakeApi({});
    const store = new ConversationsStore(api, { items: [convo(1, "2026-01-02T00:00:00Z")], nextCursor: null });
    expect(store.getSnapshot().items.length).toBe(1);
    expect(store.getSnapshot().status).toBe("ready");
    expect(calls).toEqual([]);
  });

  test("a new or active conversation moves to the top", () => {
    const { api } = fakeApi({});
    const store = new ConversationsStore(api, {
      items: [convo(1, "2026-01-03T00:00:00Z"), convo(2, "2026-01-02T00:00:00Z")],
      nextCursor: null,
    });
    store.upsert(convo(3, "2026-01-04T00:00:00Z", "New"));
    store.upsert({ ...convo(2, "2026-01-05T00:00:00Z"), title: "Renamed by activity" });
    expect(store.getSnapshot().items.map((item) => item.title)).toEqual(["Renamed by activity", "New", "Chat 1"]);
  });

  test("rename is optimistic and rolls back when refused — the error is not swallowed", async () => {
    const { api } = fakeApi({}, { failRename: true });
    const store = new ConversationsStore(api, { items: [convo(1, "2026-01-01T00:00:00Z", "Old")], nextCursor: null });
    const renaming = store.rename(convo(1, "").id, "New title");
    expect(store.getSnapshot().items[0]?.title).toBe("New title");
    await expect(renaming).rejects.toBeInstanceOf(ApiError);
    expect(store.getSnapshot().items[0]?.title).toBe("Old");
  });

  test("a rename wins over a stream's older copy of the conversation, until the next refresh", async () => {
    const first = convo(1, "2026-01-02T00:00:00Z", "New chat");
    const { api } = fakeApi({ "": { items: [convo(1, "2026-01-04T00:00:00Z", "From the server")], nextCursor: null } });
    const store = new ConversationsStore(api, { items: [first], nextCursor: null });
    await store.rename(first.id, "My biology notes");
    // The reply's `done`, read just before the rename was saved, carries the automatic title.
    store.upsert({ ...first, title: "Photosynthesis Explained", updatedAt: "2026-01-03T00:00:00Z" });
    expect(store.getSnapshot().items[0]?.title).toBe("My biology notes");
    expect(store.getSnapshot().items[0]?.updatedAt).toBe("2026-01-03T00:00:00Z"); // activity still moves
    await store.refresh();
    expect(store.getSnapshot().items[0]?.title).toBe("From the server");
    store.upsert({ ...first, title: "Named elsewhere" });
    expect(store.getSnapshot().items[0]?.title).toBe("Named elsewhere");
  });

  test("a refused rename is forgotten, so the stream's title shows", async () => {
    const first = convo(1, "2026-01-02T00:00:00Z", "New chat");
    const { api } = fakeApi({}, { failRename: true });
    const store = new ConversationsStore(api, { items: [first], nextCursor: null });
    await expect(store.rename(first.id, "Mine")).rejects.toThrow();
    store.upsert({ ...first, title: "Photosynthesis Explained" });
    expect(store.getSnapshot().items[0]?.title).toBe("Photosynthesis Explained");
  });

  test("an empty or unchanged title is not sent", async () => {
    const { api, calls } = fakeApi({});
    const store = new ConversationsStore(api, { items: [convo(1, "2026-01-01T00:00:00Z", "Same")], nextCursor: null });
    await store.rename(convo(1, "").id, "   ");
    await store.rename(convo(1, "").id, "Same");
    expect(calls).toEqual([]);
  });

  test("load more appends the next page without duplicates", async () => {
    const { api } = fakeApi({
      c1: { items: [convo(2, "2026-01-01T00:00:00Z"), convo(3, "2025-12-31T00:00:00Z")], nextCursor: null },
    });
    const store = new ConversationsStore(api, {
      items: [convo(1, "2026-01-02T00:00:00Z"), convo(2, "2026-01-01T00:00:00Z")],
      nextCursor: "c1",
    });
    await store.loadMore();
    expect(store.getSnapshot().items.map((item) => item.id)).toEqual([convo(1, "").id, convo(2, "").id, convo(3, "").id]);
    expect(store.getSnapshot().nextCursor).toBeNull();
  });

  test("refresh replaces the first page (deletions in another tab disappear)", async () => {
    const { api } = fakeApi({ "": { items: [convo(2, "2026-01-05T00:00:00Z")], nextCursor: null } });
    const store = new ConversationsStore(api, {
      items: [convo(1, "2026-01-03T00:00:00Z"), convo(2, "2026-01-02T00:00:00Z")],
      nextCursor: null,
    });
    await store.refresh();
    expect(store.getSnapshot().items.map((item) => item.id)).toEqual([convo(2, "").id]);
  });

  test("focus refreshes are throttled", async () => {
    let now = 1_000_000;
    const { api, calls } = fakeApi({ "": { items: [], nextCursor: null } });
    const store = new ConversationsStore(api, { items: [], nextCursor: null }, () => now);
    await store.refresh(30_000);
    expect(calls).toEqual([]);
    now += 31_000;
    await store.refresh(30_000);
    expect(calls).toEqual(["list:"]);
  });

  test("a failed first load reports an error instead of an empty list", async () => {
    const { api } = fakeApi({});
    const store = new ConversationsStore(api, null);
    expect(store.getSnapshot().status).toBe("loading");
    await store.refresh();
    expect(store.getSnapshot().status).toBe("error");
  });

  test("page size matches the server-rendered first page", () => {
    expect(PAGE_SIZE).toBe(30);
  });
});
