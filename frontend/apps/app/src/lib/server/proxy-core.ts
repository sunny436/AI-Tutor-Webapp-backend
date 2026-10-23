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
 *   TOKENS      The session lives in Better Auth's httpOnly cookie (lib/auth). Its
 *               signature is verified here, then the token is attached; the browser
 *               never sees it.
 *   IDENTITY    X-Forwarded-For is set from `cf-connecting-ip` only. The API trusts the
 *               FIRST address it is given, so passing a client-supplied chain on would
 *               let anyone choose the IP that sign-in throttling counts.
 *   STREAMS     SSE is passed through unbuffered. When the browser goes away the
 *               upstream request is aborted, which the API treats as "stop".
 *   ERRORS      Error envelopes keep `code`, `requestId`, field names and their
 *               machine-readable reasons only; backend wording never reaches the page
 *               (the UI has its own copy per code). A `version_conflict` also keeps
 *               `current`: the caller's own resource as it is now.
 *   SIZE        Request bodies are capped at the API's own 64 KB limit before any
 *               forwarding.
 *   FILES       A route with `upload` takes a raw file instead of JSON: only its listed
 *               content types, only up to its own cap, read only once the session
 *               cookie is known to be there. A route with `file` answers with bytes of
 *               its listed types; the API's cache headers pass only when they are
 *               `private` (a browser may keep a content-addressed photo, a shared
 *               cache never), and the file can never run as a page (nosniff, a
 *               sandboxing CSP). Files are read whole, a few at a time (the rest
 *               queue), like uploads.
 *   VOICE       Voice mode's routes (`voice`: a recording, a sentence's audio) have a class of
 *               their own, never behind the file queues: small, and waited on mid-conversation.
 *
 * Pure (no Next.js imports) so it is unit-tested directly.
 */

import { matchRoute } from "@/lib/api/routes";
import { clearedSessionCookies, readSessionToken } from "./cookies";
import { publicOrigin, publicProtocol } from "./public-origin";

export const MAX_BODY_BYTES = 64 * 1024;
const JSON_TIMEOUT_MS = 30_000;
const MUTATIONS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

export type ProxyDeps = {
  apiBaseUrl: string;
  /** BETTER_AUTH_SECRET: the session cookie's signature is checked with it. */
  cookieSecret: string;
  fetchImpl?: typeof fetch;
  requestId?: () => string;
  jsonTimeoutMs?: number;
  log?: (line: string) => void;
};

type FieldError = { field: string; reason?: string };

/** A machine-readable reason (`too_small`, `string_too_long`), never a sentence. */
const REASON = /^[a-z][a-z0-9_]{0,63}$/;

function envelope(
  status: number,
  code: string,
  requestId: string,
  extra: { fields?: FieldError[]; current?: object; cookies?: string[] } = {},
): Response {
  const headers = new Headers({
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Request-ID": requestId,
  });
  for (const cookie of extra.cookies ?? []) headers.append("Set-Cookie", cookie);
  const error: Record<string, unknown> = { code, requestId };
  if (extra.fields?.length) error.fields = extra.fields;
  if (extra.current) error.current = extra.current;
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
async function readBody(request: Request, limit: number): Promise<Uint8Array | "too_large"> {
  const declared = Number(request.headers.get("content-length") ?? "");
  if (Number.isFinite(declared) && declared > limit) return "too_large";
  if (!request.body) return new Uint8Array(0);
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
  return bytes;
}

/** `image/png; charset=x` → `image/png`. */
function mediaType(value: string | null): string {
  return (value ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
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

/**
 * Uploads larger than a JSON body are buffered whole before they are forwarded (a 25 MB file is
 * about twice that in memory while it is read), so only this many run at once in this process;
 * the rest get 503 `busy` straight away, before anything is read.
 */
export const UPLOADS_IN_FLIGHT_MAX = 2;
let uploadsInFlight = 0;

/**
 * Files sent back (a PDF or image preview, up to 25 MB) are buffered whole too, so only this many
 * are read at once; the rest wait their turn rather than fail (a preview is worth the wait).
 */
export const FILES_IN_FLIGHT_MAX = 3;
let filesInFlight = 0;
const fileQueue: (() => void)[] = [];

async function fileSlot(): Promise<() => void> {
  if (filesInFlight < FILES_IN_FLIGHT_MAX) filesInFlight += 1;
  else await new Promise<void>((resolve) => fileQueue.push(resolve));
  // A freed slot is handed straight to the next in line, so the count never overshoots.
  return () => {
    const next = fileQueue.shift();
    if (next) next();
    else filesInFlight -= 1;
  };
}

/**
 * Voice mode's requests at once in this process: a recording (up to 1 MiB) or a sentence's audio (up to 2 MB)
 * each, so at most about 40 MB in memory. The API's own caps are 8 transcriptions and 16 sentences at once in all,
 * so this is what both may use; beyond it, 503 `busy` before anything is read. Their own class because the
 * upload queue turned 6 of 8 students talking at once away as `busy` (e2e stack, 2026-10-23).
 */
export const VOICE_IN_FLIGHT_MAX = 24;
let voiceInFlight = 0;

export async function proxyRequest(request: Request, segments: string[], deps: ProxyDeps): Promise<Response> {
  const spec = matchRoute(request.method.toUpperCase(), `/v1/${segments.join("/")}`)?.spec;
  if (spec?.voice) {
    if (voiceInFlight >= VOICE_IN_FLIGHT_MAX) {
      return envelope(503, "busy", deps.requestId?.() ?? crypto.randomUUID().replace(/-/g, ""));
    }
    voiceInFlight += 1;
    try {
      return await forward(request, segments, deps);
    } finally {
      voiceInFlight -= 1; // success, failure, a timeout or the browser leaving (its abort ends forward)
    }
  }
  if (spec?.file) {
    const release = await fileSlot();
    try {
      return await forward(request, segments, deps);
    } finally {
      release();
    }
  }
  const upload = spec?.upload;
  if (!upload || upload.maxBytes <= MAX_BODY_BYTES) return forward(request, segments, deps);
  if (uploadsInFlight >= UPLOADS_IN_FLIGHT_MAX) {
    return envelope(503, "busy", deps.requestId?.() ?? crypto.randomUUID().replace(/-/g, ""));
  }
  uploadsInFlight += 1;
  try {
    return await forward(request, segments, deps);
  } finally {
    uploadsInFlight -= 1;
  }
}

async function forward(request: Request, segments: string[], deps: ProxyDeps): Promise<Response> {
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

  const token = await readSessionToken(request.headers.get("cookie"), https, deps.cookieSecret);
  if (spec.auth && !token) {
    return envelope(401, "unauthorized", requestId, { cookies: clearedSessionCookies(https) });
  }

  let body: string | Uint8Array | undefined;
  let bodyType: string | undefined;
  if (spec.upload) {
    bodyType = mediaType(request.headers.get("content-type"));
    if (!spec.upload.types.includes(bodyType)) return envelope(415, "unsupported_media_type", requestId);
    const read = await readBody(request, spec.upload.maxBytes);
    if (read === "too_large") return envelope(413, "payload_too_large", requestId);
    body = read;
  } else if (spec.body) {
    const type = request.headers.get("content-type") ?? "";
    if (!type.toLowerCase().startsWith("application/json")) {
      return envelope(415, "validation_error", requestId);
    }
    const read = await readBody(request, MAX_BODY_BYTES);
    if (read === "too_large") return envelope(413, "payload_too_large", requestId);
    body = new TextDecoder().decode(read);
    bodyType = "application/json";
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
    Accept: spec.stream ? "text/event-stream" : spec.file ? spec.file.types.join(", ") : "application/json",
    "X-Request-ID": requestId,
  });
  if (body !== undefined && bodyType) headers.set("Content-Type", bodyType);
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

  // A 401 usually means the session is over — drop the cookie. EXCEPT
  // `invalid_credentials`: the API also answers a wrong *current* password
  // (change password, delete account) with 401, and signing someone out for a
  // typo in a confirmation field would be absurd.
  if (upstream.status === 401) {
    if (timer) clearTimeout(timer);
    let code = "unauthorized";
    try {
      const parsed = JSON.parse(await upstream.text()) as { error?: { code?: unknown } };
      if (parsed.error?.code === "invalid_credentials") code = "invalid_credentials";
    } catch {
      // unreadable 401: treat as a lost session
    }
    if (code === "invalid_credentials") return envelope(401, code, requestId);
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

  if (spec.file && upstream.ok) {
    const type = mediaType(upstream.headers.get("content-type"));
    let bytes: ArrayBuffer;
    try {
      if (!spec.file.types.includes(type)) throw new Error("unexpected content type");
      bytes = await upstream.arrayBuffer();
    } catch {
      await upstream.body?.cancel().catch(() => undefined);
      log(`[bff] ${key} upstream file refused ${requestId}`);
      return envelope(502, "service_unavailable", requestId);
    } finally {
      if (timer) clearTimeout(timer);
    }
    const cache = upstream.headers.get("cache-control") ?? "";
    responseHeaders.set("Cache-Control", /^\s*private\b/i.test(cache) ? cache : "no-store");
    responseHeaders.set("Content-Type", type);
    responseHeaders.set("X-Content-Type-Options", "nosniff");
    responseHeaders.set("Content-Security-Policy", "default-src 'none'; sandbox");
    const etag = upstream.headers.get("etag");
    if (etag) responseHeaders.set("ETag", etag);
    return new Response(bytes, { status: 200, headers: responseHeaders });
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
    let fields: FieldError[] | undefined;
    let current: object | undefined;
    try {
      const parsed = JSON.parse(text) as { error?: { code?: unknown; fields?: unknown; current?: unknown } };
      if (typeof parsed.error?.code === "string") code = parsed.error.code;
      if (Array.isArray(parsed.error?.fields)) {
        fields = parsed.error.fields.flatMap((entry) => {
          const { field, reason } = entry as { field?: unknown; reason?: unknown };
          if (typeof field !== "string") return [];
          return typeof reason === "string" && REASON.test(reason) ? [{ field, reason }] : [{ field }];
        });
      }
      // A version conflict carries the caller's own resource as it is now, so the page can
      // re-apply its edit without another round trip. Nothing else passes.
      const latest = parsed.error?.current;
      if (code === "version_conflict" && latest && typeof latest === "object" && !Array.isArray(latest)) {
        current = latest;
      }
    } catch {
      // non-JSON error body: the status says enough
    }
    if (upstream.status >= 500) log(`[bff] ${key} ${upstream.status} ${requestId}`);
    return envelope(upstream.status, code, requestId, { fields, current });
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
