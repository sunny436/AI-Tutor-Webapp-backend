/**
 * The BFF: the only path from a browser to the chat API.
 *
 *   browser ──/api/v1/...──► this proxy ──/v1/... + Bearer <session>──► API (127.0.0.1)
 *
 * What it guarantees (backend docs/frontend-integration.md, plus the audit):
 *
 *   ALLOWLIST   Only routes in `lib/api/routes.ts` are forwarded; ids must be UUIDs;
 *               only listed query params pass. Anything else is a 404 — this is not
 *               an open proxy.
 *   CSRF        Mutations must carry an `Origin` equal to the public origin (or, with
 *               no Origin, `Sec-Fetch-Site: same-origin`) and a JSON content type.
 *   TOKENS      The session lives in an httpOnly cookie. It is attached here and
 *               stripped from every response; the browser never sees it.
 *   IDENTITY    X-Forwarded-For is set from `cf-connecting-ip` only. The API trusts the
 *               FIRST address it is given, so passing a client-supplied chain on would
 *               let anyone choose the IP that sign-in throttling counts.
 *   STREAMS     SSE is passed through unbuffered. When the browser goes away the
 *               upstream request is aborted, which the API treats as "stop".
 *   ERRORS      Error envelopes keep `code`, `requestId` and field names only; backend
 *               wording never reaches the page (the UI has its own copy per code).
 *   SIZE        Request bodies are capped at the API's own 64 KB limit before any
 *               forwarding.
 *
 * Pure (no Next.js imports) so it is unit-tested directly.
 */

import { matchRoute } from "@/lib/api/routes";
import { clearedSessionCookies, readSessionToken, sessionCookie } from "./cookies";
import { publicOrigin, publicProtocol } from "./public-origin";

export const MAX_BODY_BYTES = 64 * 1024;
const JSON_TIMEOUT_MS = 30_000;
const MUTATIONS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

export type ProxyDeps = {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
  requestId?: () => string;
  jsonTimeoutMs?: number;
  log?: (line: string) => void;
};

function envelope(
  status: number,
  code: string,
  requestId: string,
  extra: { fields?: { field: string }[]; cookies?: string[] } = {},
): Response {
  const headers = new Headers({
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Request-ID": requestId,
  });
  for (const cookie of extra.cookies ?? []) headers.append("Set-Cookie", cookie);
  const error: Record<string, unknown> = { code, requestId };
  if (extra.fields?.length) error.fields = extra.fields;
  return new Response(JSON.stringify({ error }), { status, headers });
}

/** Status → contract code, for upstream errors that arrive without a usable body. */
function codeForStatus(status: number): string {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 413:
      return "payload_too_large";
    case 422:
      return "validation_error";
    case 429:
      return "rate_limited";
    case 502:
    case 503:
    case 504:
      return "service_unavailable";
    default:
      return "internal_error";
  }
}

const IPV4 = /^(?:\d{1,3}\.){3}\d{1,3}$/;
const IPV6 = /^[0-9a-f:]+$/i;

function clientIp(headers: Headers): string | null {
  const ip = headers.get("cf-connecting-ip")?.trim();
  if (!ip) return null;
  return IPV4.test(ip) || (ip.includes(":") && IPV6.test(ip)) ? ip : null;
}

export function isSameOrigin(request: Request): boolean {
  const expected = publicOrigin(request.headers, request.url);
  const origin = request.headers.get("origin");
  if (origin) return origin === expected;
  return request.headers.get("sec-fetch-site") === "same-origin";
}

/** Read a body, refusing more than `limit` bytes without buffering the excess. */
async function readBody(request: Request, limit: number): Promise<string | "too_large"> {
  const declared = Number(request.headers.get("content-length") ?? "");
  if (Number.isFinite(declared) && declared > limit) return "too_large";
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel().catch(() => undefined);
      return "too_large";
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

/** Pass an upstream stream through; cancelling ours aborts theirs. */
function passThrough(upstream: ReadableStream<Uint8Array>, abort: () => void): ReadableStream<Uint8Array> {
  const reader = upstream.getReader();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) controller.close();
        else controller.enqueue(value);
      } catch (error) {
        controller.error(error);
      }
    },
    cancel(reason) {
      abort();
      reader.cancel(reason).catch(() => undefined);
    },
  });
}

export async function proxyRequest(request: Request, segments: string[], deps: ProxyDeps): Promise<Response> {
  const requestId = deps.requestId?.() ?? crypto.randomUUID().replace(/-/g, "");
  const method = request.method.toUpperCase();
  const path = `/v1/${segments.join("/")}`;
  const https = publicProtocol(request.headers, request.url) === "https";
  const log = deps.log ?? ((line: string) => console.warn(line));

  const match = matchRoute(method, path);
  if (!match) return envelope(404, "not_found", requestId);
  const { key, spec } = match;

  if (MUTATIONS.has(method) && !isSameOrigin(request)) {
    log(`[bff] ${key} 403 cross-origin ${requestId}`);
    return envelope(403, "forbidden", requestId);
  }

  let body: string | undefined;
  if (spec.body) {
    const type = request.headers.get("content-type") ?? "";
    if (!type.toLowerCase().startsWith("application/json")) {
      return envelope(415, "validation_error", requestId);
    }
    const read = await readBody(request, MAX_BODY_BYTES);
    if (read === "too_large") return envelope(413, "payload_too_large", requestId);
    body = read;
  }

  const token = readSessionToken(request.headers.get("cookie"), https);
  if (spec.auth && !token) {
    return envelope(401, "unauthorized", requestId, { cookies: clearedSessionCookies(https) });
  }

  const incoming = new URL(request.url);
  const query = new URLSearchParams();
  for (const name of spec.query ?? []) {
    const value = incoming.searchParams.get(name);
    if (value !== null && value !== "") query.set(name, value);
  }
  const search = query.toString();
  const target = `${deps.apiBaseUrl}${path}${search ? `?${search}` : ""}`;

  const headers = new Headers({
    Accept: spec.stream ? "text/event-stream" : "application/json",
    "X-Request-ID": requestId,
  });
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (spec.auth && token) headers.set("Authorization", `Bearer ${token}`);
  const ip = clientIp(request.headers);
  if (ip) headers.set("X-Forwarded-For", ip);
  const agent = request.headers.get("user-agent");
  if (agent) headers.set("User-Agent", agent);

  // One controller for everything that should end the upstream request: the
  // browser leaving, our stream being cancelled, or (JSON only) a timeout.
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (request.signal.aborted) abort();
  else request.signal.addEventListener("abort", abort, { once: true });
  const timer = spec.stream ? null : setTimeout(abort, deps.jsonTimeoutMs ?? JSON_TIMEOUT_MS);

  let upstream: Response;
  try {
    upstream = await (deps.fetchImpl ?? fetch)(target, {
      method,
      headers,
      body,
      signal: controller.signal,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    if (timer) clearTimeout(timer);
    log(`[bff] ${key} upstream unreachable ${requestId}`);
    return envelope(503, "service_unavailable", requestId);
  }

  const responseHeaders = new Headers({ "Cache-Control": "no-store", "X-Request-ID": requestId });

  // A 401 means the session is over, wherever it came from: drop the cookie.
  if (upstream.status === 401) {
    if (timer) clearTimeout(timer);
    await upstream.body?.cancel().catch(() => undefined);
    return envelope(401, "unauthorized", requestId, { cookies: clearedSessionCookies(https) });
  }

  if (spec.stream && upstream.ok) {
    const type = upstream.headers.get("content-type") ?? "";
    if (!upstream.body || !type.includes("text/event-stream")) {
      await upstream.body?.cancel().catch(() => undefined);
      return envelope(502, "service_unavailable", requestId);
    }
    responseHeaders.set("Content-Type", "text/event-stream; charset=utf-8");
    responseHeaders.set("Cache-Control", "no-cache, no-transform");
    responseHeaders.set("X-Accel-Buffering", "no");
    return new Response(passThrough(upstream.body, abort), { status: 200, headers: responseHeaders });
  }

  let text: string;
  try {
    text = await upstream.text();
  } catch {
    log(`[bff] ${key} upstream body failed ${requestId}`);
    return envelope(502, "service_unavailable", requestId);
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (!upstream.ok) {
    let code = codeForStatus(upstream.status);
    let fields: { field: string }[] | undefined;
    try {
      const parsed = JSON.parse(text) as { error?: { code?: unknown; fields?: unknown } };
      if (typeof parsed.error?.code === "string") code = parsed.error.code;
      if (Array.isArray(parsed.error?.fields)) {
        fields = parsed.error.fields
          .map((entry) => (entry as { field?: unknown }).field)
          .filter((field): field is string => typeof field === "string")
          .map((field) => ({ field }));
      }
    } catch {
      // non-JSON error body: the status says enough
    }
    if (upstream.status >= 500) log(`[bff] ${key} ${upstream.status} ${requestId}`);
    return envelope(upstream.status, code, requestId, { fields });
  }

  if (spec.session === "issue") {
    let user: unknown;
    let session: { token?: unknown; expiresAt?: unknown } | undefined;
    try {
      ({ user, session } = JSON.parse(text) as { user: unknown; session: typeof session });
    } catch {
      return envelope(502, "service_unavailable", requestId);
    }
    if (typeof session?.token !== "string" || typeof session.expiresAt !== "string" || !user) {
      return envelope(502, "service_unavailable", requestId);
    }
    responseHeaders.set("Content-Type", "application/json");
    responseHeaders.append("Set-Cookie", sessionCookie(session.token, session.expiresAt, https));
    // The token is deliberately NOT in the body: the browser only ever gets `user`.
    return new Response(JSON.stringify({ user }), { status: upstream.status, headers: responseHeaders });
  }

  if (spec.session === "clear") {
    for (const cookie of clearedSessionCookies(https)) responseHeaders.append("Set-Cookie", cookie);
  }

  if (upstream.status === 204 || !text) {
    return new Response(null, { status: upstream.status === 200 ? 204 : upstream.status, headers: responseHeaders });
  }
  responseHeaders.set("Content-Type", "application/json");
  return new Response(text, { status: upstream.status, headers: responseHeaders });
}
