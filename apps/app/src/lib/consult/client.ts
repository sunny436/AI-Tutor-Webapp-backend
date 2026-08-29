/**
 * The single place the dashboard talks to the AI backend.
 *
 * Every call here goes to a same-origin Next.js route, never to the Python
 * backend directly - the route re-derives a fresh session token server-side.
 * The `AI_BACKEND_URL` export that used to live here is gone: its last consumer
 * was the speak-aloud button. The Python host is still reached, but only from
 * `server-session.ts`, which reads the env var itself.
 */

import type { ConsultContext, ConsultRequest, ConsultResult } from "./types";

/**
 * Which brain answers: the local Python backend, or the central API.
 *
 * "local" is the default deliberately. This is a whole-brain transplant on a
 * live product, and the site not going down is a standing requirement — so the
 * central path ships switched off, and one env var turns it on or back off
 * without a code change or a rebuild of anything but the bundle.
 *
 * Delete this switch, and the `local` branch with it, once the central API has
 * been proven on real traffic. A fallback nobody has flipped in months is dead
 * code pretending to be safety.
 */
export const CONSULT_PROVIDER =
  process.env.NEXT_PUBLIC_CONSULT_PROVIDER === "central"
    ? "central"
    : process.env.NEXT_PUBLIC_CONSULT_PROVIDER === "mock"
      ? "mock"
      : "local";

/**
 * Which bot this frontend is. Sent on every turn; the backend validates it.
 *
 * One central Python backend serves several frontends, and `bot_id` is what
 * selects the knowledge base, so it belongs in the frontend's own configuration
 * rather than being inferred server-side. An unregistered value is a 400 — never
 * a silent fallback to somebody else's corpus.
 *
 * Defaults to "ayurveda" so an unset env var keeps this deployment working.
 */
export const BOT_ID = process.env.NEXT_PUBLIC_BOT_ID || "ayurveda";

/**
 * A canned conversation, for building UI without a backend.
 *
 * Deliberately a third branch of the switch that already exists rather than a
 * separate mock server: the seam is proven, and this way switching between mock
 * and real is one env var with no code change — which is the whole point of
 * `NEXT_PUBLIC_CONSULT_PROVIDER` existing.
 *
 * A frontend developer needs no Python, no Convex, no API key and no knowledge
 * of how retrieval works to change the chat UI.
 */
function mockResult(request: ConsultRequest): ConsultResult {
  const said = (request.problem || request.freeText || "").trim();
  const turns = (request.context?.chat_history?.length ?? 0) / 2;
  const done = turns >= 2;

  return {
    kind: done ? "answer" : "chat",
    condition: "Acidity",
    message: "",
    intake: null,
    answer: done
      ? "**Root Cause**\nEating late and lying down soon after weakens digestion, so acid rises instead of settling.\n\n**Changes To Make**\nFinish dinner by 8pm. Sit upright for 20 minutes after eating.\n\n**When To See A Doctor**\nBlood in vomit, black stools, or difficulty swallowing need a doctor promptly."
      : said
        ? "Samajh gaya. Ye kab se ho raha hai, aur khaane ke baad zyada hota hai?"
        : "Namaste! Bataiye, kya takleef hai?",
    context: {
      ...(request.context ?? {
        v: 1,
        greeted: true,
        last_answer: "",
        round: 0,
        problem: said,
        needs_second_round: false,
        asked: [],
        answers: {},
        notes: [],
      }),
      phase: done ? "completed" : "gathering",
      condition: "Acidity",
      chat_history: [
        ...(request.context?.chat_history ?? []),
        { role: "user" as const, text: said },
        { role: "assistant" as const, text: "…" },
      ],
    } as ConsultContext,
    sources: done
      ? [
          { section: "Trusted Ayurveda / Yoga knowledge", source: "knowledge:acidity.md", score: 0.59 },
          { section: "Trusted Ayurveda / Yoga knowledge", source: "knowledge:gas-bloating.md", score: 0.54 },
        ]
      : [],
  };
}

/**
 * Both providers go through OUR server. Same-origin, no token, no key.
 *
 * The browser used to post straight to the Python backend carrying a Convex
 * token, and that is what produced the reported "AI service unavailable (401)":
 * `@convex-dev/auth` only refreshes a token when Convex's own client hits an
 * auth error, and a hand-written fetch to another host is invisible to it — so
 * `useAuthToken()` kept handing back one that had expired an hour earlier.
 *
 * The middleware refreshes the auth cookie on `/api/*`, so the server always
 * reads a live token. A browser that holds no token cannot hold a stale one.
 */
const CONSULT_ENDPOINT = "/api/consult";
const CONSULT_STREAM_ENDPOINT = "/api/consult/stream";
const UPLOAD_ENDPOINT = "/api/upload";

/** Add `Authorization` only when a token exists, so anonymous calls stay clean. */
function authHeaders(
  token: string | null | undefined,
  base: Record<string, string> = {},
): Record<string, string> {
  return token ? { ...base, Authorization: `Bearer ${token}` } : base;
}

/** Thrown when the AI backend is unreachable or returns a non-2xx. */
export class ConsultUnavailableError extends Error {
  /**
   * `session` means the login expired, not that the AI is down.
   *
   * Worth separating because the two need opposite reactions from the user. A
   * real outage means wait; an expired token means reload, and waiting for it to
   * fix itself never works. Reported live as "AI service unavailable (401)"
   * while the backend log said plainly `token rejected: Signature has expired`,
   * which sent the reader looking at the AI instead of at their own session.
   */
  readonly reason: "service" | "session" | "signed_out";

  constructor(
    message: string,
    reason: "service" | "session" | "signed_out" = "service",
  ) {
    super(message);
    this.name = "ConsultUnavailableError";
    this.reason = reason;
  }
}

/** A Convex token lives a limited time; a tab left open outlives it. */
const SESSION_EXPIRED_MESSAGE =
  "Your session has expired. Please refresh the page to continue.";

/**
 * Read the server's 401 and decide which of the two it is.
 *
 * `signed_out` means both auth cookies are gone because a token refresh failed —
 * the session is over and only signing in fixes it. Anything else is a token
 * that has merely gone stale, where a reload is enough. The distinction matters
 * because the wrong advice wastes the reader's time: reloading a dead session
 * just lands them on the login page without explaining why.
 */
async function classify401(response: Response): Promise<ConsultUnavailableError> {
  try {
    const body = (await response.clone().json()) as { reason?: string; error?: string };
    if (body?.reason === "signed_out") {
      return new ConsultUnavailableError(
        body.error || "Your session has ended. Please sign in again.",
        "signed_out",
      );
    }
  } catch {
    // A 401 without a JSON body is still a 401; fall through.
  }
  return new ConsultUnavailableError(SESSION_EXPIRED_MESSAGE, "session");
}

/**
 * Advance the consultation by one turn.
 *
 * The backend is stateless: whatever `context` it returned last time is echoed
 * back here, and it re-derives everything from that plus the freshly submitted
 * answers.
 */
/** Every outbound turn carries the bot it is for. Added in one place, not four. */
function withBot(request: ConsultRequest): ConsultRequest {
  return { bot_id: BOT_ID, ...request };
}

export async function postConsult(
  request: ConsultRequest,
  signal?: AbortSignal,
  token?: string | null,
): Promise<ConsultResult> {
  if (CONSULT_PROVIDER === "mock") return mockResult(request);

  let response: Response;
  try {
    response = await fetch(CONSULT_ENDPOINT, {
      method: "POST",
      // The Convex login token, when there is one. The backend verifies it and
      // uses the subject to decide whose uploaded reports may be searched -
      // without it the consultation still works, but only against the shared
      // knowledge base. Get it from `useAuthToken()` in a client component.
      headers: authHeaders(token, { "Content-Type": "application/json" }),
      body: JSON.stringify(withBot(request)),
      signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new ConsultUnavailableError(
      "Could not reach the AI backend. Start it with run_backend.bat.",
    );
  }

  if (response.status === 401) {
    throw await classify401(response);
  }
  if (!response.ok) {
    throw new ConsultUnavailableError(
      `The AI backend returned an error (${response.status}). Please try again.`,
    );
  }
  return (await response.json()) as ConsultResult;
}

/**
 * The same turn as `postConsult`, but the prose arrives as it is written.
 *
 * `onToken` is a preview and nothing more. The resolved `ConsultResult` is the
 * authoritative answer and is what the caller should store — a caller that
 * ignored every token would still end up with exactly the right transcript.
 * That matters because tokens can stop arriving (a dropped connection, a model
 * that cannot stream) and the stored conversation must not depend on them.
 *
 * Falls back to `postConsult` if the stream cannot be opened or ends without a
 * result, so a backend without the endpoint, or a proxy that buffers the
 * response into uselessness, degrades to the behaviour that already worked.
 */
export async function postConsultStream(
  request: ConsultRequest,
  onToken: (text: string) => void,
  signal?: AbortSignal,
  token?: string | null,
): Promise<ConsultResult> {
  // The mock does not stream. `postConsult` is the documented fallback for a
  // backend that cannot, so the UI already handles this path.
  if (CONSULT_PROVIDER === "mock") return postConsult(request, signal, token);

  let response: Response;
  try {
    response = await fetch(CONSULT_STREAM_ENDPOINT, {
      method: "POST",
      headers: authHeaders(token, { "Content-Type": "application/json" }),
      body: JSON.stringify(withBot(request)),
      signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    return postConsult(request, signal, token);
  }

  // An expired token will not become valid by being asked a second time, so
  // this one case skips the retry and reports what actually happened.
  if (response.status === 401) {
    throw await classify401(response);
  }

  if (!response.ok || !response.body) {
    return postConsult(request, signal, token);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  let result: ConsultResult | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffered += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line. Anything after the last one is
      // a partial frame and stays in the buffer until the rest arrives — parsing
      // it early would drop characters mid-word.
      const frames = buffered.split("\n\n");
      buffered = frames.pop() ?? "";

      for (const frame of frames) {
        const event = frame.match(/^event:\s*(.+)$/m)?.[1]?.trim();
        const data = frame.match(/^data:\s*(.+)$/m)?.[1];
        if (!event || !data) continue;
        if (event === "token") {
          try {
            onToken((JSON.parse(data) as { text: string }).text);
          } catch {
            // A malformed preview frame is not worth failing the turn over.
          }
        } else if (event === "done") {
          result = JSON.parse(data) as ConsultResult;
        } else if (event === "error") {
          throw new ConsultUnavailableError("The AI backend could not finish that turn.");
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  // No `done` frame means the stream died partway. The tokens already shown are
  // not a result we can store, so ask again the ordinary way.
  return result ?? (await postConsult(request, signal, token));
}

export type UploadResult = {
  filename: string;
  /** Characters of text recovered. 0 means the file could not be read. */
  chars: number;
  /**
   * The extracted text — and the ONLY copy of it.
   *
   * This replaced `indexed`, and the difference is not cosmetic. The backend
   * used to embed the file into a per-user index and report how many chunks it
   * had stored; it now extracts the text, hands it back, and keeps NOTHING.
   * Whatever the caller does not hold on to is gone as soon as this response is
   * discarded, and no later turn can recover it.
   *
   * So this is state the client owns, and `ConsultRequest.documents` is how it
   * gets back to the assistant.
   */
  text: string;
  /**
   * True when the file was too long to extract whole, so `text` is a prefix.
   *
   * Distinct from `ConsultResult.documentTruncated`, which is about the text
   * being cut on the way INTO retrieval. Either can happen without the other.
   */
  truncated: boolean;
};

/**
 * Send a report to the backend to be read and added to this user's library.
 *
 * Without a token the text is still extracted and returned, but nothing is
 * stored - there is no user to store it against.
 */
export async function uploadDocument(
  file: File,
  token?: string | null,
  signal?: AbortSignal,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type on purpose: the browser must set it itself so it can add
  // the multipart boundary. Setting it by hand produces a body the server
  // cannot parse.
  // Through OUR server, like every other call. It used to post straight to the
  // backend with a token the page had no way to refresh — the same bug the
  // consult route was moved to fix, just rarer because uploads are rarer.
  const response = await fetch(UPLOAD_ENDPOINT, {
    method: "POST",
    headers: authHeaders(token),
    body: form,
    signal,
  }).catch((error) => {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new ConsultUnavailableError("Could not reach the AI backend.");
  });

  if (!response.ok) {
    throw new ConsultUnavailableError(
      `Upload failed (${response.status}). Please try again.`,
    );
  }
  return (await response.json()) as UploadResult;
}

