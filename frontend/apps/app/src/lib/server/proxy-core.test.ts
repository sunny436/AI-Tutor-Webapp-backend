import { describe, expect, test } from "bun:test";
import { serializeSignedCookie } from "better-call";

import { PLAIN_COOKIE, SECURE_COOKIE } from "./cookies";
import { MAX_BODY_BYTES, VOICE_IN_FLIGHT_MAX, proxyRequest } from "./proxy-core";

const SECRET = "a-test-secret-that-is-long-enough-for-better-auth";
/** A session token as Better Auth makes them (32 letters and digits). */
const TOKEN = "tok123AbCdEfGhIjKlMnOpQrStUvWxYz";
/** The session cookie as Better Auth writes it: TOKEN, signed. */
const SIGNED = (await serializeSignedCookie(SECURE_COOKIE, TOKEN, SECRET)).split(";")[0] as string;

const API = "http://127.0.0.1:4000";
const APP = "https://chat.example.com";
const CID = "11111111-1111-4111-8111-111111111111";
const MID = "22222222-2222-4222-8222-222222222222";

type Call = { url: string; init: RequestInit };

function upstream(respond: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetchImpl = (async (url: string, init: RequestInit) => {
    const call = { url, init };
    calls.push(call);
    return respond(call);
  }) as unknown as typeof fetch;
  return { calls, fetchImpl };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** A browser request arriving through the Cloudflare tunnel (HTTPS at the edge). */
function browser(
  method: string,
  path: string,
  options: { body?: string; headers?: Record<string, string>; signal?: AbortSignal; cookie?: string | null } = {},
): Request {
  const headers = new Headers({
    host: "chat.example.com",
    "x-forwarded-proto": "https",
    origin: APP,
    "sec-fetch-site": "same-origin",
    "user-agent": "TestBrowser/1.0",
    ...(options.body !== undefined ? { "content-type": "application/json" } : {}),
    ...options.headers,
  });
  if (options.cookie !== null) headers.set("cookie", options.cookie ?? SIGNED);
  // Next.js hands the route the internal URL (plain HTTP on loopback).
  return new Request(`http://localhost:3000/api${path}`, {
    method,
    headers,
    body: options.body,
    signal: options.signal,
  });
}

const segments = (path: string) => path.replace(/^\/v1\//, "").split("?")[0]?.split("/") ?? [];

function run(request: Request, path: string, fetchImpl: typeof fetch, extra: Record<string, unknown> = {}) {
  return proxyRequest(request, segments(path), {
    apiBaseUrl: API,
    cookieSecret: SECRET,
    fetchImpl,
    requestId: () => "req1",
    log: () => undefined,
    ...extra,
  });
}

describe("allowlist", () => {
  test("unknown routes, wrong methods and non-UUID ids are 404 without calling the API", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    for (const [method, path] of [
      ["GET", "/v1/me/settings"],
      ["POST", "/v1/chat"],
      ["DELETE", "/v1/conversations"],
      ["GET", "/v1/conversations/not-a-uuid"],
      ["GET", "/v1/../health"],
    ] as const) {
      const response = await run(browser(method, path), path, fetchImpl);
      expect(response.status).toBe(404);
    }
    expect(calls.length).toBe(0);
  });

  test("forwards only allowlisted query params", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, { items: [], nextCursor: null }));
    const path = "/v1/conversations?limit=30&cursor=abc&evil=1";
    await run(browser("GET", path), "/v1/conversations", fetchImpl);
    expect(calls[0]?.url).toBe(`${API}/v1/conversations?limit=30&cursor=abc`);
  });
});

describe("CSRF", () => {
  test("a mutation from another origin is refused", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    const request = browser("PATCH", `/v1/conversations/${CID}`, {
      body: JSON.stringify({ title: "x" }),
      headers: { origin: "https://evil.example" },
    });
    expect((await run(request, `/v1/conversations/${CID}`, fetchImpl)).status).toBe(403);
    expect(calls.length).toBe(0);
  });

  test("a mutation with no Origin needs Sec-Fetch-Site: same-origin", async () => {
    const { fetchImpl } = upstream(() => new Response(null, { status: 204 }));
    const headers = new Headers({ host: "chat.example.com", "x-forwarded-proto": "https", cookie: SIGNED });
    const bare = new Request("http://localhost:3000/api/v1/auth/logout", { method: "POST", headers });
    expect((await run(bare, "/v1/auth/logout", fetchImpl)).status).toBe(403);

    headers.set("sec-fetch-site", "same-origin");
    const sameSite = new Request("http://localhost:3000/api/v1/auth/logout", { method: "POST", headers });
    expect((await run(sameSite, "/v1/auth/logout", fetchImpl)).status).toBe(204);
  });

  test("the public origin comes from the forwarded headers, not the internal URL", async () => {
    const { fetchImpl } = upstream(() => new Response(null, { status: 204 }));
    const request = browser("POST", "/v1/auth/logout", { headers: { origin: "http://localhost:3000" } });
    expect((await run(request, "/v1/auth/logout", fetchImpl)).status).toBe(403);
  });

  test("a body route requires a JSON content type", async () => {
    const { fetchImpl } = upstream(() => json(200, {}));
    const request = browser("POST", "/v1/me/email/change", {
      body: "newEmail=a",
      headers: { "content-type": "application/x-www-form-urlencoded" },
    });
    expect((await run(request, "/v1/me/email/change", fetchImpl)).status).toBe(415);
  });
});

describe("size limit", () => {
  test("bodies over 64 KB are refused before forwarding", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    const request = browser("POST", "/v1/chat/stream", {
      body: JSON.stringify({ message: "x".repeat(MAX_BODY_BYTES + 1) }),
    });
    const response = await run(request, "/v1/chat/stream", fetchImpl);
    expect(response.status).toBe(413);
    expect(calls.length).toBe(0);
  });
});

describe("session and identity", () => {
  test("an authenticated route without the cookie is 401 without calling the API", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    const response = await run(browser("GET", "/v1/me", { cookie: null }), "/v1/me", fetchImpl);
    expect(response.status).toBe(401);
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe("unauthorized");
    expect(calls.length).toBe(0);
  });

  test("on HTTPS a planted plain cookie is not a session", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    const response = await run(browser("GET", "/v1/me", { cookie: `${PLAIN_COOKIE}=planted` }), "/v1/me", fetchImpl);
    expect(response.status).toBe(401);
    expect(calls.length).toBe(0);
  });

  test("forwards the bearer token, request id, user agent and the Cloudflare client IP only", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, { id: "u" }));
    const request = browser("GET", "/v1/me", {
      headers: { "cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "6.6.6.6, 203.0.113.9" },
    });
    await run(request, "/v1/me", fetchImpl);
    const sent = new Headers(calls[0]?.init.headers);
    expect(sent.get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(sent.get("x-request-id")).toBe("req1");
    expect(sent.get("user-agent")).toBe("TestBrowser/1.0");
    expect(sent.get("x-forwarded-for")).toBe("203.0.113.9");
    expect(sent.get("cookie")).toBeNull();
    expect(sent.get("origin")).toBeNull();
  });

  test("a client-supplied X-Forwarded-For is never passed on", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    await run(browser("GET", "/v1/me", { headers: { "x-forwarded-for": "6.6.6.6" } }), "/v1/me", fetchImpl);
    expect(new Headers(calls[0]?.init.headers).get("x-forwarded-for")).toBeNull();
  });

  test("an unauthenticated route never forwards a stale token", async () => {
    const { calls, fetchImpl } = upstream(() => new Response(JSON.stringify({ status: "accepted" }), { status: 202 }));
    await run(browser("POST", "/v1/auth/signup", { body: JSON.stringify({ email: "a@b.c", password: "x" }) }), "/v1/auth/signup", fetchImpl);
    expect(new Headers(calls[0]?.init.headers).get("authorization")).toBeNull();
  });
});

describe("session cookie handling", () => {
  test("a token without Better Auth's signature is not a session: 401, the API is never called", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, { id: "u1" }));
    for (const cookie of [`${SECURE_COOKIE}=${TOKEN}`, `${SECURE_COOKIE}=${TOKEN}.${"A".repeat(43)}=`]) {
      const response = await run(browser("GET", "/v1/me", { cookie }), "/v1/me", fetchImpl);
      expect(response.status).toBe(401);
    }
    expect(calls.length).toBe(0);
  });

  test("logout and account deletion clear the cookie", async () => {
    const { fetchImpl } = upstream(() => new Response(null, { status: 204 }));
    const logout = await run(browser("POST", "/v1/auth/logout"), "/v1/auth/logout", fetchImpl);
    expect(logout.headers.get("set-cookie")).toContain("Max-Age=0");
    const del = await run(browser("DELETE", "/v1/me", { body: JSON.stringify({ password: "p" }) }), "/v1/me", fetchImpl);
    expect(del.status).toBe(204);
    expect(del.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  test("an upstream 401 `unauthorized` clears the cookie", async () => {
    const { fetchImpl } = upstream(() => json(401, { error: { code: "unauthorized", message: "expired" } }));
    const response = await run(browser("GET", "/v1/me"), "/v1/me", fetchImpl);
    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  test("a wrong current password (401 invalid_credentials) does NOT sign the user out", async () => {
    const { fetchImpl } = upstream(() => json(401, { error: { code: "invalid_credentials" } }));
    const request = browser("DELETE", "/v1/me", { body: JSON.stringify({ password: "wrong" }) });
    const response = await run(request, "/v1/me", fetchImpl);
    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe("invalid_credentials");
  });
});

describe("errors", () => {
  test("upstream envelopes keep code, requestId and field names — not backend wording", async () => {
    const { fetchImpl } = upstream(() =>
      json(422, {
        error: {
          code: "validation_error",
          message: "internal wording",
          requestId: "up1",
          fields: [{ field: "password", reason: "String should have at least 8 characters" }],
        },
      }),
    );
    const request = browser("POST", "/v1/me/email/change", { body: JSON.stringify({ newEmail: "a@b.c", password: "x" }) });
    const response = await run(request, "/v1/me/email/change", fetchImpl);
    const body = await response.text();
    expect(response.status).toBe(422);
    expect(body).not.toContain("internal wording");
    expect(body).not.toContain("at least 8");
    expect(JSON.parse(body)).toEqual({
      error: { code: "validation_error", requestId: "req1", fields: [{ field: "password" }] },
    });
  });

  test("a non-JSON upstream error still becomes an envelope", async () => {
    const { fetchImpl } = upstream(() => new Response("<html>Bad gateway</html>", { status: 502 }));
    const response = await run(browser("GET", "/v1/me"), "/v1/me", fetchImpl);
    expect(response.status).toBe(502);
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe("service_unavailable");
  });

  test("an unreachable API is a 503 envelope", async () => {
    const { fetchImpl } = upstream(() => {
      throw new TypeError("ECONNREFUSED");
    });
    const response = await run(browser("GET", "/v1/me"), "/v1/me", fetchImpl);
    expect(response.status).toBe(503);
  });

  test("a hung JSON call times out instead of hanging the page", async () => {
    const { fetchImpl } = upstream(
      ({ init }) =>
        new Promise<Response>((_, reject) =>
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
        ),
    );
    const response = await run(browser("GET", "/v1/me"), "/v1/me", fetchImpl, { jsonTimeoutMs: 20 });
    expect(response.status).toBe(503);
  });
});

describe("streaming", () => {
  test("SSE is passed through with no-buffering headers", async () => {
    const { fetchImpl } = upstream(
      () =>
        new Response('event: token\ndata: {"text":"hi"}\n\n', {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
    );
    const request = browser("POST", "/v1/chat/stream", { body: JSON.stringify({ message: "hi" }) });
    const response = await run(request, "/v1/chat/stream", fetchImpl);
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(await response.text()).toBe('event: token\ndata: {"text":"hi"}\n\n');
  });

  test("cancelling the browser side aborts the upstream request", async () => {
    let upstreamSignal: AbortSignal | undefined;
    const { fetchImpl } = upstream(({ init }) => {
      upstreamSignal = init.signal ?? undefined;
      return new Response(new ReadableStream({ start() {} }), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    });
    const request = browser("POST", `/v1/conversations/${CID}/regenerate/stream`);
    const response = await run(request, `/v1/conversations/${CID}/regenerate/stream`, fetchImpl);
    await response.body?.cancel();
    expect(upstreamSignal?.aborted).toBe(true);
  });

  test("the browser disconnecting (request.signal) aborts the upstream request", async () => {
    const browserSide = new AbortController();
    let upstreamSignal: AbortSignal | undefined;
    const { fetchImpl } = upstream(({ init }) => {
      upstreamSignal = init.signal ?? undefined;
      return new Response(new ReadableStream({ start() {} }), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    });
    const request = browser("POST", "/v1/chat/stream", {
      body: JSON.stringify({ message: "hi" }),
      signal: browserSide.signal,
    });
    await run(request, "/v1/chat/stream", fetchImpl);
    browserSide.abort();
    expect(upstreamSignal?.aborted).toBe(true);
  });

  test("a stream route answered with non-SSE content is not passed through", async () => {
    const { fetchImpl } = upstream(() => json(200, { oops: true }));
    const response = await run(browser("POST", `/v1/messages/${MID}/cancel`), `/v1/messages/${MID}/cancel`, fetchImpl);
    // cancel is a JSON route: passes through normally
    expect(response.status).toBe(200);
    const stream = await run(
      browser("POST", "/v1/chat/stream", { body: JSON.stringify({ message: "x" }) }),
      "/v1/chat/stream",
      fetchImpl,
    );
    expect(stream.status).toBe(502);
  });
});

describe("files", () => {
  const PHOTO = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]);
  const HASH = "0123456789abcdef0123456789abcdef";

  function upload(body: BodyInit, type: string, extra: { cookie?: string | null } = {}): Request {
    const headers = new Headers({ host: "chat.example.com", "x-forwarded-proto": "https", origin: APP, "content-type": type });
    if (extra.cookie !== null) headers.set("cookie", extra.cookie ?? SIGNED);
    return new Request("http://localhost:3000/api/v1/me/avatar", { method: "PUT", headers, body });
  }

  test("a photo upload is forwarded as the same bytes and type", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, { avatar: { url: `/v1/me/avatar?v=${HASH}` } }));
    const response = await run(upload(PHOTO, "image/png"), "/v1/me/avatar", fetchImpl);
    expect(response.status).toBe(200);
    const sent = calls[0]?.init;
    expect(new Headers(sent?.headers).get("content-type")).toBe("image/png");
    expect(new Headers(sent?.headers).get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(Array.from(sent?.body as Uint8Array)).toEqual(Array.from(PHOTO));
  });

  test("an upload of another type, too large, or without a session never reaches the API", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    expect((await run(upload(PHOTO, "image/gif"), "/v1/me/avatar", fetchImpl)).status).toBe(415);
    expect((await run(upload("{}", "application/json"), "/v1/me/avatar", fetchImpl)).status).toBe(415);
    const huge = new Uint8Array(5 * 1024 * 1024 + 1);
    expect((await run(upload(huge, "image/jpeg"), "/v1/me/avatar", fetchImpl)).status).toBe(413);
    const anonymous = await run(upload(PHOTO, "image/png", { cookie: null }), "/v1/me/avatar", fetchImpl);
    expect(anonymous.status).toBe(401);
    expect(calls.length).toBe(0);
  });

  test("only two uploads are read at once: a third gets 503 busy, and the slots free up afterwards", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { calls, fetchImpl } = upstream(async () => {
      await gate;
      return json(200, {});
    });
    const first = run(upload(PHOTO, "image/png"), "/v1/me/avatar", fetchImpl);
    const second = run(upload(PHOTO, "image/png"), "/v1/me/avatar", fetchImpl);
    await new Promise((resolve) => setTimeout(resolve, 5));
    const third = await run(upload(PHOTO, "image/png"), "/v1/me/avatar", fetchImpl);
    expect(third.status).toBe(503);
    expect(((await third.json()) as { error: { code: string } }).error.code).toBe("busy");
    release();
    expect((await first).status).toBe(200);
    expect((await second).status).toBe(200);
    expect((await run(upload(PHOTO, "image/png"), "/v1/me/avatar", fetchImpl)).status).toBe(200);
    expect(calls.length).toBe(3);
  });

  test("the unsupported type has its own code", async () => {
    const { fetchImpl } = upstream(() => json(200, {}));
    const response = await run(upload(PHOTO, "text/html"), "/v1/me/avatar", fetchImpl);
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe("unsupported_media_type");
  });

  test("an upload still needs a same-origin request", async () => {
    const { calls, fetchImpl } = upstream(() => json(200, {}));
    const request = upload(PHOTO, "image/png");
    request.headers.set("origin", "https://evil.example");
    expect((await run(request, "/v1/me/avatar", fetchImpl)).status).toBe(403);
    expect(calls.length).toBe(0);
  });

  test("a photo is passed back as bytes with the API's private cache headers", async () => {
    const headers = {
      "Content-Type": "image/webp",
      "Cache-Control": "private, max-age=31536000, immutable",
      ETag: `"${HASH}"`,
    };
    const { calls, fetchImpl } = upstream(() => new Response(PHOTO, { status: 200, headers }));
    const response = await run(browser("GET", `/v1/me/avatar?v=${HASH}&other=1`), "/v1/me/avatar", fetchImpl);
    expect(calls[0]?.url).toBe(`${API}/v1/me/avatar?v=${HASH}`);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/webp");
    expect(response.headers.get("cache-control")).toBe("private, max-age=31536000, immutable");
    expect(response.headers.get("etag")).toBe(`"${HASH}"`);
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("content-security-policy")).toBe("default-src 'none'; sandbox");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(PHOTO);
  });

  test("a shared-cacheable or unexpected file is never passed on as such", async () => {
    const shared = { "Content-Type": "image/webp", "Cache-Control": "public, max-age=60" };
    const publicCache = upstream(() => new Response(PHOTO, { status: 200, headers: shared }));
    const cached = await run(browser("GET", `/v1/me/avatar?v=${HASH}`), "/v1/me/avatar", publicCache.fetchImpl);
    expect(cached.headers.get("cache-control")).toBe("no-store");

    const page = { "Content-Type": "text/html" };
    const html = upstream(() => new Response("<script>x</script>", { status: 200, headers: page }));
    const refused = await run(browser("GET", `/v1/me/avatar?v=${HASH}`), "/v1/me/avatar", html.fetchImpl);
    expect(refused.status).toBe(502);
    expect(await refused.text()).not.toContain("script");
  });

  test("a missing photo is an ordinary uncached error", async () => {
    const { fetchImpl } = upstream(() => json(404, { error: { code: "not_found", message: "Not found." } }));
    const response = await run(browser("GET", `/v1/me/avatar?v=${HASH}`), "/v1/me/avatar", fetchImpl);
    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});

describe("voice", () => {
  function recording(signal?: AbortSignal): Request {
    const headers = new Headers({ host: "chat.example.com", "x-forwarded-proto": "https", origin: APP, "content-type": "audio/webm" });
    headers.set("cookie", SIGNED);
    return new Request("http://localhost:3000/api/v1/voice/transcriptions?seconds=3", {
      method: "POST",
      headers,
      body: new Uint8Array(200 * 1024), // over the 64 KB at which uploads take the 2 file slots
      signal,
    });
  }
  const path = "/v1/voice/transcriptions?seconds=3";

  test("voice has its own class: far more than the 2 upload slots at once, then 503 busy before reading", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { calls, fetchImpl } = upstream(async () => {
      await gate;
      return json(200, { text: "", seconds: 3 });
    });
    const held = Array.from({ length: VOICE_IN_FLIGHT_MAX }, () => run(recording(), path, fetchImpl));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(calls.length).toBe(VOICE_IN_FLIGHT_MAX); // all of them reached the API, none queued behind files
    const over = await run(recording(), path, fetchImpl);
    expect(over.status).toBe(503);
    expect(((await over.json()) as { error: { code: string } }).error.code).toBe("busy");
    expect(calls.length).toBe(VOICE_IN_FLIGHT_MAX); // refused before anything was read or sent on
    // Files are not held up by voice, nor voice by files.
    const photo = new Request("http://localhost:3000/api/v1/me/avatar", {
      method: "PUT",
      headers: { host: "chat.example.com", "x-forwarded-proto": "https", origin: APP, "content-type": "image/png", cookie: SIGNED },
      body: new Uint8Array(70 * 1024),
    });
    const quick = upstream(() => json(200, {}));
    expect((await run(photo, "/v1/me/avatar", quick.fetchImpl)).status).toBe(200);
    release();
    for (const response of await Promise.all(held)) expect(response.status).toBe(200);
    expect((await run(recording(), path, fetchImpl)).status).toBe(200); // the slots are free again
  });

  test("a student who goes away frees the slot at once", async () => {
    const { fetchImpl } = upstream(
      (call) =>
        new Promise<Response>((_, reject) => {
          call.init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const leaving = Array.from({ length: VOICE_IN_FLIGHT_MAX }, () => new AbortController());
    const pending = leaving.map((controller) => run(recording(controller.signal), path, fetchImpl));
    await new Promise((resolve) => setTimeout(resolve, 20));
    for (const controller of leaving) controller.abort();
    await Promise.all(pending);
    const after = upstream(() => json(200, { text: "", seconds: 3 }));
    expect((await run(recording(), path, after.fetchImpl)).status).toBe(200);
  });
});

describe("error details", () => {
  test("machine-readable field reasons pass, sentences do not", async () => {
    const fields = [
      { field: "image", reason: "too_small" },
      { field: "set.displayName", reason: "The name must not be blank." },
    ];
    const { fetchImpl } = upstream(() => json(422, { error: { code: "validation_error", fields } }));
    const request = browser("PATCH", "/v1/me/profile", { body: JSON.stringify({ version: 0 }) });
    const body = (await (await run(request, "/v1/me/profile", fetchImpl)).json()) as { error: { fields: unknown } };
    expect(body.error.fields).toEqual([{ field: "image", reason: "too_small" }, { field: "set.displayName" }]);
  });

  test("a version conflict keeps the current resource; other errors never carry one", async () => {
    const current = { id: CID, displayName: "Asha", profileVersion: 3 };
    const conflict = upstream(() => json(409, { error: { code: "version_conflict", message: "x", current } }));
    const request = () => browser("PATCH", "/v1/me/profile", { body: JSON.stringify({ version: 1 }) });
    const response = await run(request(), "/v1/me/profile", conflict.fetchImpl);
    expect(response.status).toBe(409);
    expect(((await response.json()) as { error: { current: unknown } }).error.current).toEqual(current);

    const other = upstream(() => json(409, { error: { code: "conflict", current } }));
    const plain = (await (await run(request(), "/v1/me/profile", other.fetchImpl)).json()) as { error: object };
    expect(plain.error).toEqual({ code: "conflict", requestId: "req1" });
  });
});
