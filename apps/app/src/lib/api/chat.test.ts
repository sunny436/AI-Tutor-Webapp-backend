import { describe, expect, test } from "bun:test";
import { type StreamHandlers, streamChat, streamRegenerate } from "./chat";
import { ApiError } from "./errors";
import { onUnauthorized } from "./http";

const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";
const ASSISTANT_ID = "22222222-2222-4222-8222-222222222222";

const META = {
  conversationId: CONVERSATION_ID,
  conversation: { id: CONVERSATION_ID, title: "Hi", createdAt: "t", updatedAt: "t" },
  userMessage: null,
  assistantMessageId: ASSISTANT_ID,
  replacesMessageId: null,
};
const DONE = {
  message: {
    id: ASSISTANT_ID,
    conversationId: CONVERSATION_ID,
    role: "assistant",
    content: "Hello there",
    status: "complete",
    createdAt: "t",
  },
  conversation: META.conversation,
};

const encoder = new TextEncoder();
const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

type FakeOptions = {
  status?: number;
  contentType?: string;
  body?: unknown;
  /** Error the stream after sending all chunks (a dropped connection). */
  failAfter?: boolean;
  /** Keep the stream open after the chunks (so the caller has to abort). */
  hang?: boolean;
};

function fakeFetch(chunks: (string | Uint8Array)[], options: FakeOptions = {}) {
  const calls: { url: string; init: RequestInit }[] = [];
  const impl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const status = options.status ?? 200;
    if (status !== 200) {
      return new Response(JSON.stringify(options.body ?? {}), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
        }
        init.signal?.addEventListener("abort", () =>
          controller.error(new DOMException("The operation was aborted.", "AbortError")),
        );
        if (options.failAfter) controller.error(new TypeError("network connection lost"));
        else if (!options.hang) controller.close();
      },
    });
    return new Response(stream, {
      status,
      headers: { "Content-Type": options.contentType ?? "text/event-stream" },
    });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

function recorder() {
  const log: string[] = [];
  const handlers: StreamHandlers = {
    onMeta: (meta) => log.push(`meta:${meta.assistantMessageId}`),
    onToken: (token) => log.push(`token:${token.text}`),
    onDone: (done) => log.push(`done:${done.message.status}`),
    onError: (failure) => log.push(`error:${failure.code}`),
  };
  return { log, handlers };
}

describe("streamChat", () => {
  test("meta → tokens → done", async () => {
    const { impl, calls } = fakeFetch([
      ": open\n\n",
      frame("meta", META),
      frame("token", { text: "Hello" }),
      ": keepalive\n\n",
      frame("token", { text: " there" }),
      frame("done", DONE),
    ]);
    const { log, handlers } = recorder();
    const outcome = await streamChat({ message: "Hi" }, handlers, { fetchImpl: impl });
    expect(outcome).toBe("done");
    expect(log).toEqual([`meta:${ASSISTANT_ID}`, "token:Hello", "token: there", "done:complete"]);
    expect(calls[0]?.url).toBe("/api/v1/chat/stream");
  });

  test("a new chat sends only `message` (the API rejects unknown fields)", async () => {
    const { impl, calls } = fakeFetch([frame("done", DONE)]);
    await streamChat({ message: "Hi", conversationId: null }, {}, { fetchImpl: impl });
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({ message: "Hi" });
  });

  test("an existing chat sends conversationId and message only", async () => {
    const { impl, calls } = fakeFetch([frame("done", DONE)]);
    await streamChat({ message: "Hi", conversationId: CONVERSATION_ID }, {}, { fetchImpl: impl });
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({
      conversationId: CONVERSATION_ID,
      message: "Hi",
    });
  });

  test("error event ends the reply (no done)", async () => {
    const { impl } = fakeFetch([
      frame("meta", META),
      frame("token", { text: "par" }),
      frame("error", { code: "llm_timeout", message: "x", retryable: true, messageId: ASSISTANT_ID }),
    ]);
    const { log, handlers } = recorder();
    expect(await streamChat({ message: "Hi" }, handlers, { fetchImpl: impl })).toBe("error");
    expect(log.at(-1)).toBe("error:llm_timeout");
  });

  test("a stream that ends without done/error is interrupted — and fetch is called ONCE", async () => {
    const { impl, calls } = fakeFetch([frame("meta", META), frame("token", { text: "Hel" })]);
    const { log, handlers } = recorder();
    expect(await streamChat({ message: "Hi" }, handlers, { fetchImpl: impl })).toBe("interrupted");
    expect(calls.length).toBe(1);
    expect(log).toEqual([`meta:${ASSISTANT_ID}`, "token:Hel"]);
  });

  test("a dropped connection mid-stream is interrupted — still one fetch", async () => {
    const { impl, calls } = fakeFetch([frame("meta", META), frame("token", { text: "a" })], {
      failAfter: true,
    });
    expect(await streamChat({ message: "Hi" }, {}, { fetchImpl: impl })).toBe("interrupted");
    expect(calls.length).toBe(1);
  });

  test("a complete final frame without its blank line is accepted", async () => {
    const tail = frame("done", DONE).trimEnd();
    const { impl } = fakeFetch([frame("meta", META), tail]);
    const { log, handlers } = recorder();
    expect(await streamChat({ message: "Hi" }, handlers, { fetchImpl: impl })).toBe("done");
    expect(log.at(-1)).toBe("done:complete");
  });

  test("a truncated final frame is not acted on", async () => {
    const { impl } = fakeFetch([frame("meta", META), 'event: done\ndata: {"message":{"id"']);
    expect(await streamChat({ message: "Hi" }, {}, { fetchImpl: impl })).toBe("interrupted");
  });

  test("malformed and unknown events are ignored", async () => {
    const { impl } = fakeFetch([
      frame("meta", META),
      "event: token\ndata: {not json\n\n",
      frame("citation", { source: "future" }),
      frame("token", { text: "ok" }),
      frame("done", DONE),
    ]);
    const { log, handlers } = recorder();
    expect(await streamChat({ message: "Hi" }, handlers, { fetchImpl: impl })).toBe("done");
    expect(log).toEqual([`meta:${ASSISTANT_ID}`, "token:ok", "done:complete"]);
  });

  test("a multi-byte character split across network chunks survives", async () => {
    const bytes = encoder.encode(frame("token", { text: "héllo 👋" }));
    const cut = bytes.indexOf(0xf0) + 2; // in the middle of the emoji
    const { impl } = fakeFetch([bytes.slice(0, cut), bytes.slice(cut), frame("done", DONE)]);
    const { log, handlers } = recorder();
    await streamChat({ message: "Hi" }, handlers, { fetchImpl: impl });
    expect(log[0]).toBe("token:héllo 👋");
  });

  test("aborting mid-stream resolves `aborted`", async () => {
    const controller = new AbortController();
    const { impl } = fakeFetch([frame("meta", META)], { hang: true });
    const handlers: StreamHandlers = { onMeta: () => controller.abort() };
    expect(await streamChat({ message: "Hi" }, handlers, { fetchImpl: impl, signal: controller.signal })).toBe(
      "aborted",
    );
  });

  test("HTTP errors before the stream opens reject with the contract code", async () => {
    const { impl } = fakeFetch([], {
      status: 409,
      body: { error: { code: "conflict", message: "busy", requestId: "r1" } },
    });
    const error = await streamChat({ message: "Hi" }, {}, { fetchImpl: impl }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("conflict");
    expect((error as ApiError).requestId).toBe("r1");
  });

  test("a 401 notifies the unauthorized listeners", async () => {
    let notified = 0;
    const off = onUnauthorized(() => {
      notified += 1;
    });
    const { impl } = fakeFetch([], { status: 401, body: { error: { code: "unauthorized" } } });
    await streamChat({ message: "Hi" }, {}, { fetchImpl: impl }).catch(() => undefined);
    off();
    expect(notified).toBe(1);
  });

  test("a network failure rejects with network_error", async () => {
    const impl = (async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const error = await streamChat({ message: "Hi" }, {}, { fetchImpl: impl }).catch((e) => e);
    expect((error as ApiError).code).toBe("network_error");
  });

  test("a non-SSE success response is treated as unavailable, not parsed", async () => {
    const { impl } = fakeFetch([], { contentType: "text/html" });
    const error = await streamChat({ message: "Hi" }, {}, { fetchImpl: impl }).catch((e) => e);
    expect((error as ApiError).code).toBe("service_unavailable");
  });
});

describe("streamRegenerate", () => {
  test("posts to the conversation's regenerate stream with no body", async () => {
    const { impl, calls } = fakeFetch([frame("done", DONE)]);
    await streamRegenerate(CONVERSATION_ID, {}, { fetchImpl: impl });
    expect(calls[0]?.url).toBe(`/api/v1/conversations/${CONVERSATION_ID}/regenerate/stream`);
    expect(calls[0]?.init.body).toBeUndefined();
  });

  test("refuses a non-UUID conversation id before any request", async () => {
    const { impl, calls } = fakeFetch([]);
    await expect(streamRegenerate("../../v1/me", {}, { fetchImpl: impl })).rejects.toThrow();
    expect(calls.length).toBe(0);
  });
});
