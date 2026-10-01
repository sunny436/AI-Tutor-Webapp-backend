import { describe, expect, test } from "bun:test";
import type { StreamHandlers, StreamOutcome } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import type { ChatRequest, Conversation, Message, MessagePage } from "@/lib/api/types";
import { type ChatApi, ChatStore } from "./chat-store";

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

const conversation = (id: string, title = "Chat"): Conversation => ({
  id,
  title,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
});
const message = (id: string, conversationId: string, role: "user" | "assistant", content: string, status: Message["status"] = "complete"): Message => ({
  id,
  conversationId,
  role,
  content,
  status,
  createdAt: "2026-01-01T00:00:00Z",
});

type PendingStream = {
  kind: "chat" | "regenerate";
  request?: ChatRequest;
  conversationId?: string;
  handlers: StreamHandlers;
  signal?: AbortSignal;
  resolve: (outcome: StreamOutcome) => void;
  reject: (error: unknown) => void;
};

class FakeApi implements ChatApi {
  streams: PendingStream[] = [];
  cancelled: string[] = [];
  deleted: string[] = [];
  listCalls: { id: string; before?: string | null }[] = [];
  pages = new Map<string, MessagePage>();
  feedbackCalls: string[] = [];
  failFeedback = false;

  private open(stream: Omit<PendingStream, "resolve" | "reject">): Promise<StreamOutcome> {
    return new Promise((resolve, reject) => {
      this.streams.push({ ...stream, resolve, reject });
      stream.signal?.addEventListener("abort", () => resolve("aborted"));
    });
  }
  streamChat = (request: ChatRequest, handlers: StreamHandlers, options: { signal?: AbortSignal }) =>
    this.open({ kind: "chat", request, handlers, signal: options.signal });
  streamRegenerate = (conversationId: string, handlers: StreamHandlers, options: { signal?: AbortSignal }) =>
    this.open({ kind: "regenerate", conversationId, handlers, signal: options.signal });
  cancelMessage = async (id: string) => {
    this.cancelled.push(id);
    return { status: "cancelled" };
  };
  listMessages = async (id: string, options: { before?: string | null }) => {
    this.listCalls.push({ id, before: options.before });
    const page = this.pages.get(`${id}:${options.before ?? ""}`);
    if (!page) throw new ApiError(404, "not_found");
    return page;
  };
  setFeedback = async (id: string, rating: string) => {
    this.feedbackCalls.push(`${id}:${rating}`);
    if (this.failFeedback) throw new ApiError(503, "service_unavailable");
  };
  clearFeedback = async (id: string) => {
    this.feedbackCalls.push(`${id}:clear`);
  };
  deleteConversation = async (id: string) => {
    this.deleted.push(id);
  };
  respondToAssessment = async (): Promise<never> => {
    throw new ApiError(404, "not_found");
  };
}

/** A scheduler the test drives: nothing flushes until `tick()`. */
function manualScheduler() {
  let queue: (() => void)[] = [];
  return {
    schedule: (run: () => void) => {
      queue.push(run);
      return () => {
        queue = queue.filter((item) => item !== run);
      };
    },
    tick: () => {
      const current = queue;
      queue = [];
      for (const run of current) run();
    },
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function setup(options: { stopGraceMs?: number } = {}) {
  const api = new FakeApi();
  const clock = manualScheduler();
  const created: { conversation: Conversation; draftKey: string }[] = [];
  const updated: Conversation[] = [];
  const store = new ChatStore({
    api,
    schedule: clock.schedule,
    stopGraceMs: options.stopGraceMs ?? 3000,
    onConversationCreated: (c, draftKey) => created.push({ conversation: c, draftKey }),
    onConversationUpdated: (c) => updated.push(c),
  });
  return { api, clock, store, created, updated };
}

function meta(conversationId: string, assistantId: string, userMessage: Message | null, replaces: string | null = null) {
  return {
    conversationId,
    conversation: conversation(conversationId),
    userMessage,
    assistantMessageId: assistantId,
    replacesMessageId: replaces,
  };
}

describe("a new chat", () => {
  test("draft → meta re-keys to the server's id; tokens batch; done is authoritative", async () => {
    const { api, clock, store, created, updated } = setup();
    const draft = store.freshDraftKey();
    store.activeKey = draft;

    const sending = store.send(draft, "  Hello  ");
    const entry = store.getEntry(draft);
    expect(entry?.order.length).toBe(1);
    expect(store.getMessage(draft, entry?.order[0] ?? "")?.content).toBe("Hello");
    expect(entry?.stream?.phase).toBe("starting");
    expect(api.streams[0]?.request).toEqual({ conversationId: null, message: "Hello" });

    const user = message(uuid(1), A, "user", "Hello");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), user));

    expect(store.resolve(draft)).toBe(A);
    expect(store.activeKey).toBe(A);
    expect(store.getEntry(A)?.order).toEqual([uuid(1), uuid(2)]);
    expect(store.getEntry(draft)).toBe(store.getEntry(A));
    expect(store.getEntry(A)?.stream).toEqual({ phase: "streaming", assistantId: uuid(2) });
    expect(created.map((item) => [item.conversation.id, item.draftKey])).toEqual([[A, draft]]);

    api.streams[0]?.handlers.onToken?.({ text: "Hi" });
    api.streams[0]?.handlers.onToken?.({ text: " there" });
    expect(store.getMessage(A, uuid(2))?.content).toBe(""); // batched, not yet flushed
    clock.tick();
    expect(store.getMessage(A, uuid(2))?.content).toBe("Hi there");

    api.streams[0]?.handlers.onDone?.({
      message: message(uuid(2), A, "assistant", "Hi there!"),
      conversation: conversation(A, "Hello"),
    });
    api.streams[0]?.resolve("done");
    await sending;

    expect(store.getMessage(A, uuid(2))?.content).toBe("Hi there!");
    expect(store.getMessage(A, uuid(2))?.status).toBe("complete");
    expect(store.getEntry(A)?.stream).toBeNull();
    expect(updated.at(-1)?.title).toBe("Hello");
    expect(api.streams.length).toBe(1);
  });

  test("a token notifies only the streaming message's subscribers", async () => {
    const { api, clock, store } = setup();
    const draft = store.freshDraftKey();
    let entryNotifications = 0;
    let replyNotifications = 0;
    let userNotifications = 0;
    store.subscribe(draft, () => {
      entryNotifications += 1;
    });

    void store.send(draft, "Hello");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "Hello")));
    store.subscribeMessage(A, uuid(2), () => {
      replyNotifications += 1;
    });
    store.subscribeMessage(A, uuid(1), () => {
      userNotifications += 1;
    });
    const entryBefore = entryNotifications;

    for (let index = 0; index < 20; index += 1) api.streams[0]?.handlers.onToken?.({ text: "x" });
    clock.tick();

    expect(replyNotifications).toBe(1); // 20 tokens, one batched flush
    expect(userNotifications).toBe(0);
    expect(entryNotifications).toBe(entryBefore); // the list did not re-render
    expect(store.listenerCount("entry", A)).toBe(1); // the draft's listener followed the re-key
  });

  test("two new chats started back to back stay separate", async () => {
    const { api, store } = setup();
    const first = store.freshDraftKey();
    void store.send(first, "one");
    const second = store.freshDraftKey();
    expect(second).not.toBe(first);
    void store.send(second, "two");
    expect(api.streams.length).toBe(2);
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "one")));
    api.streams[1]?.handlers.onMeta?.(meta(B, uuid(4), message(uuid(3), B, "user", "two")));
    expect(store.resolve(first)).toBe(A);
    expect(store.resolve(second)).toBe(B);
    expect(store.getEntry(A)?.order).toEqual([uuid(1), uuid(2)]);
    expect(store.getEntry(B)?.order).toEqual([uuid(3), uuid(4)]);
  });

  test("an unused draft is reused rather than piling up", () => {
    const { store } = setup();
    expect(store.freshDraftKey()).toBe(store.freshDraftKey());
  });
});

describe("per-conversation state", () => {
  async function loaded(store: ChatStore, api: FakeApi, id: string) {
    api.pages.set(`${id}:`, { items: [message(uuid(90), id, "user", "q"), message(uuid(91), id, "assistant", "a")], nextCursor: null });
    await store.ensureLoaded(id);
  }

  test("a stream in chat A never blocks chat B", async () => {
    const { api, store } = setup();
    await loaded(store, api, A);
    await loaded(store, api, B);
    void store.send(A, "long question");
    expect(store.isStreaming(A)).toBe(true);
    void store.send(B, "other question");
    expect(store.isStreaming(B)).toBe(true);
    expect(api.streams.map((stream) => stream.request?.conversationId)).toEqual([A, B]);
    // …and a second send in A while it streams is ignored.
    void store.send(A, "again");
    expect(api.streams.length).toBe(2);
  });

  test("unsubscribing (the page unmounting) does not stop the stream", async () => {
    const { api, clock, store } = setup();
    await loaded(store, api, A);
    const off = store.subscribe(A, () => undefined);
    const sending = store.send(A, "q2");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "q2")));
    off();
    api.streams[0]?.handlers.onToken?.({ text: "still coming" });
    clock.tick();
    expect(store.getMessage(A, uuid(2))?.content).toBe("still coming");
    api.streams[0]?.handlers.onDone?.({ message: message(uuid(2), A, "assistant", "still coming"), conversation: conversation(A) });
    api.streams[0]?.resolve("done");
    await sending;
    expect(api.streams[0]?.signal?.aborted).toBe(false);
  });

  test("loading a missing or foreign conversation shows not-found", async () => {
    const { store } = setup();
    await store.ensureLoaded(A);
    expect(store.getEntry(A)?.status).toBe("not_found");
  });

  test("older messages are prepended", async () => {
    const { api, store } = setup();
    api.pages.set(`${A}:`, { items: [message(uuid(3), A, "user", "new")], nextCursor: "c1" });
    api.pages.set(`${A}:c1`, { items: [message(uuid(1), A, "user", "old"), message(uuid(2), A, "assistant", "old a")], nextCursor: null });
    await store.ensureLoaded(A);
    await store.loadOlder(A);
    expect(store.getEntry(A)?.order).toEqual([uuid(1), uuid(2), uuid(3)]);
    expect(store.getEntry(A)?.nextCursor).toBeNull();
  });
});

describe("failures", () => {
  test("an `error` event marks the reply failed — no reload, no second request", async () => {
    const { api, store } = setup();
    const draft = store.freshDraftKey();
    const sending = store.send(draft, "Hello");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "Hello")));
    api.streams[0]?.handlers.onError?.({ code: "llm_timeout", message: "x", retryable: true, messageId: uuid(2), requestId: "r9" });
    api.streams[0]?.resolve("error");
    await sending;
    const reply = store.getMessage(A, uuid(2));
    expect(reply?.status).toBe("error");
    expect(reply?.failure).toEqual({ code: "llm_timeout", retryable: true, requestId: "r9" });
    expect(api.streams.length).toBe(1);
    expect(api.listCalls.length).toBe(0);
  });

  test("a dropped stream keeps what arrived and re-READS the conversation, never re-sends", async () => {
    const { api, clock, store } = setup();
    const draft = store.freshDraftKey();
    const sending = store.send(draft, "Hello");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "Hello")));
    api.streams[0]?.handlers.onToken?.({ text: "partial" });
    clock.tick();
    api.pages.set(`${A}:`, {
      items: [message(uuid(1), A, "user", "Hello"), message(uuid(2), A, "assistant", "partial answer", "cancelled")],
      nextCursor: null,
    });
    api.streams[0]?.resolve("interrupted");
    await sending;
    await settle();
    expect(api.streams.length).toBe(1);
    expect(api.listCalls).toEqual([{ id: A, before: undefined }]);
    expect(store.getMessage(A, uuid(2))?.content).toBe("partial answer");
  });

  test("a send refused before the turn existed gives the text back (409, 429, 413, offline)", async () => {
    const { api, store } = setup();
    const draft = store.freshDraftKey();
    const sending = store.send(draft, "Hello");
    api.streams[0]?.reject(new ApiError(409, "conflict"));
    await sending;
    const entry = store.getEntry(draft);
    expect(entry?.order).toEqual([]);
    expect(entry?.stream).toBeNull();
    expect(store.getDraft(draft)).toBe("Hello");
    expect(entry?.composerError?.code).toBe("conflict");
  });

  test("a message over the limit is refused locally, with no request", async () => {
    const { api, store } = setup();
    const draft = store.freshDraftKey();
    await store.send(draft, "x".repeat(16_001));
    expect(api.streams.length).toBe(0);
    expect(store.getEntry(draft)?.composerError?.code).toBe("payload_too_large");
  });
});

describe("stop, regenerate, delete", () => {
  test("stop cancels via the API and keeps reading until the persisted `done`", async () => {
    const { api, store } = setup();
    const draft = store.freshDraftKey();
    const sending = store.send(draft, "Hello");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "Hello")));
    const stopping = store.stop(A);
    expect(store.getEntry(A)?.stream?.phase).toBe("stopping");
    await stopping;
    expect(api.cancelled).toEqual([uuid(2)]);
    expect(api.streams[0]?.signal?.aborted).toBe(false); // still listening for `done`
    api.streams[0]?.handlers.onDone?.({ message: message(uuid(2), A, "assistant", "Hel", "cancelled"), conversation: conversation(A) });
    api.streams[0]?.resolve("done");
    await sending;
    expect(store.getMessage(A, uuid(2))?.status).toBe("cancelled");
    expect(store.getMessage(A, uuid(2))?.content).toBe("Hel");
    expect(store.getEntry(A)?.stream).toBeNull();
  });

  test("if `done` never comes, stop cuts the connection after the grace period", async () => {
    const { api, store } = setup({ stopGraceMs: 5 });
    const draft = store.freshDraftKey();
    const sending = store.send(draft, "Hello");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "Hello")));
    await store.stop(A);
    await sending;
    expect(api.streams[0]?.signal?.aborted).toBe(true);
    expect(store.getMessage(A, uuid(2))?.status).toBe("cancelled");
  });

  test("regenerate replaces the last reply", async () => {
    const { api, store } = setup();
    api.pages.set(`${A}:`, { items: [message(uuid(1), A, "user", "q"), message(uuid(2), A, "assistant", "old")], nextCursor: null });
    await store.ensureLoaded(A);
    expect(store.lastAssistantId(A)).toBe(uuid(2));
    const regenerating = store.regenerate(A);
    expect(api.streams[0]?.kind).toBe("regenerate");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(3), null, uuid(2)));
    expect(store.getEntry(A)?.order).toEqual([uuid(1), uuid(3)]);
    api.streams[0]?.handlers.onDone?.({ message: message(uuid(3), A, "assistant", "new"), conversation: conversation(A) });
    api.streams[0]?.resolve("done");
    await regenerating;
    expect(store.getMessage(A, uuid(3))?.content).toBe("new");
  });

  test("deleting a streaming chat stops it first and nothing writes to it afterwards", async () => {
    const { api, store, updated } = setup();
    const draft = store.freshDraftKey();
    const sending = store.send(draft, "Hello");
    api.streams[0]?.handlers.onMeta?.(meta(A, uuid(2), message(uuid(1), A, "user", "Hello")));
    const updatesBefore = updated.length;
    await store.deleteConversation(A);
    await sending;
    expect(api.cancelled).toEqual([uuid(2)]);
    expect(api.streams[0]?.signal?.aborted).toBe(true);
    expect(api.deleted).toEqual([A]);
    expect(store.getEntry(A)?.status).toBe("not_found");
    expect(store.getEntry(A)?.order).toEqual([]);
    expect(updated.length).toBe(updatesBefore);
  });

  test("sign-out aborts every stream", async () => {
    const { api, store } = setup();
    void store.send(store.freshDraftKey(), "one");
    void store.send(store.freshDraftKey(), "two");
    store.reset();
    expect(api.streams.every((stream) => stream.signal?.aborted)).toBe(true);
  });
});

describe("feedback", () => {
  test("is optimistic and rolls back if the API refuses", async () => {
    const { api, store } = setup();
    api.pages.set(`${A}:`, { items: [message(uuid(1), A, "user", "q"), message(uuid(2), A, "assistant", "a")], nextCursor: null });
    await store.ensureLoaded(A);
    await store.setFeedback(A, uuid(2), "up");
    expect(store.getMessage(A, uuid(2))?.feedback).toBe("up");
    await store.setFeedback(A, uuid(2), null);
    expect(store.getMessage(A, uuid(2))?.feedback).toBeNull();
    api.failFeedback = true;
    await expect(store.setFeedback(A, uuid(2), "down")).rejects.toBeInstanceOf(ApiError);
    expect(store.getMessage(A, uuid(2))?.feedback).toBeNull();
    expect(api.feedbackCalls).toEqual([`${uuid(2)}:up`, `${uuid(2)}:clear`, `${uuid(2)}:down`]);
  });

  test("user messages cannot be rated", async () => {
    const { api, store } = setup();
    api.pages.set(`${A}:`, { items: [message(uuid(1), A, "user", "q")], nextCursor: null });
    await store.ensureLoaded(A);
    await store.setFeedback(A, uuid(1), "up");
    expect(api.feedbackCalls).toEqual([]);
  });
});
