/**
 * The single place the dashboard talks to the AI backend.
 *
 * Replaces the hardcoded `AI_BACKEND = "http://localhost:4000"` that used to sit
 * in the consult page, so the URL is configurable per environment.
 */

import type { ConsultRequest, ConsultResult } from "./types";

export const AI_BACKEND_URL =
  process.env.NEXT_PUBLIC_AI_BACKEND_URL ?? "http://localhost:4000";

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
  process.env.NEXT_PUBLIC_CONSULT_PROVIDER === "central" ? "central" : "local";

/**
 * Where a turn is sent.
 *
 * The central path goes to OUR server, not to the central API: the API key must
 * not reach the browser, and `user_id` is an email, so identity has to be taken
 * from the verified session rather than from anything the page can edit. See
 * `app/api/consult/route.ts`.
 */
const CONSULT_ENDPOINT =
  CONSULT_PROVIDER === "central" ? "/api/consult" : `${AI_BACKEND_URL}/consult`;

const CONSULT_STREAM_ENDPOINT =
  CONSULT_PROVIDER === "central" ? "/api/consult" : `${AI_BACKEND_URL}/consult/stream`;

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
  readonly reason: "service" | "session";

  constructor(message: string, reason: "service" | "session" = "service") {
    super(message);
    this.name = "ConsultUnavailableError";
    this.reason = reason;
  }
}

/** A Convex token lives a limited time; a tab left open outlives it. */
const SESSION_EXPIRED_MESSAGE =
  "Your session has expired. Please refresh the page to continue.";

/**
 * Advance the consultation by one turn.
 *
 * The backend is stateless: whatever `context` it returned last time is echoed
 * back here, and it re-derives everything from that plus the freshly submitted
 * answers.
 */
export async function postConsult(
  request: ConsultRequest,
  signal?: AbortSignal,
  token?: string | null,
): Promise<ConsultResult> {
  let response: Response;
  try {
    response = await fetch(CONSULT_ENDPOINT, {
      method: "POST",
      // The Convex login token, when there is one. The backend verifies it and
      // uses the subject to decide whose uploaded reports may be searched -
      // without it the consultation still works, but only against the shared
      // knowledge base. Get it from `useAuthToken()` in a client component.
      headers: authHeaders(token, { "Content-Type": "application/json" }),
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new ConsultUnavailableError(
      "Could not reach the AI backend. Start it with run_backend.bat.",
    );
  }

  if (response.status === 401) {
    throw new ConsultUnavailableError(SESSION_EXPIRED_MESSAGE, "session");
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
  // Until the central API is confirmed to stream, the central path goes
  // straight to the ordinary request. That is not a degradation to paper over:
  // the whole design of this function is that `onToken` is a preview and the
  // resolved result is authoritative, so a caller that receives no tokens still
  // ends up with exactly the right transcript. The reader sees the answer arrive
  // at once instead of progressively, and nothing else differs.
  if (CONSULT_PROVIDER === "central") {
    return postConsult(request, signal, token);
  }

  let response: Response;
  try {
    response = await fetch(CONSULT_STREAM_ENDPOINT, {
      method: "POST",
      headers: authHeaders(token, { "Content-Type": "application/json" }),
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    return postConsult(request, signal, token);
  }

  // An expired token will not become valid by being asked a second time, so
  // this one case skips the retry and reports what actually happened.
  if (response.status === 401) {
    throw new ConsultUnavailableError(SESSION_EXPIRED_MESSAGE, "session");
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
  /** Chunks embedded into this user's private index. 0 when not logged in. */
  indexed: number;
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
  const response = await fetch(`${AI_BACKEND_URL}/upload`, {
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

export type TranscriptResult = {
  text: string;
  /** "english" | "hinglish" | "devanagari" - fed straight into context.language. */
  language: string;
};

/** Turn a recorded clip into text, in whatever language was actually spoken. */
export async function transcribeAudio(
  blob: Blob,
  token?: string | null,
  signal?: AbortSignal,
): Promise<TranscriptResult> {
  const form = new FormData();
  // The extension matters: the server passes the mime on to the model, and
  // MediaRecorder produces webm on Chrome but mp4 on Safari.
  const ext = blob.type.includes("mp4") ? "mp4" : "webm";
  form.append("file", blob, `clip.${ext}`);

  const response = await fetch(`${AI_BACKEND_URL}/transcribe`, {
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
      `Could not transcribe that (${response.status}).`,
    );
  }
  return (await response.json()) as TranscriptResult;
}
