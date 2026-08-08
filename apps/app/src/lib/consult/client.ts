/**
 * The single place the dashboard talks to the AI backend.
 *
 * Replaces the hardcoded `AI_BACKEND = "http://localhost:4000"` that used to sit
 * in the consult page, so the URL is configurable per environment.
 */

import type { ConsultRequest, ConsultResult } from "./types";

export const AI_BACKEND_URL =
  process.env.NEXT_PUBLIC_AI_BACKEND_URL ?? "http://localhost:4000";

/** Add `Authorization` only when a token exists, so anonymous calls stay clean. */
function authHeaders(
  token: string | null | undefined,
  base: Record<string, string> = {},
): Record<string, string> {
  return token ? { ...base, Authorization: `Bearer ${token}` } : base;
}

/** Thrown when the AI backend is unreachable or returns a non-2xx. */
export class ConsultUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConsultUnavailableError";
  }
}

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
    response = await fetch(`${AI_BACKEND_URL}/consult`, {
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

  if (!response.ok) {
    throw new ConsultUnavailableError(
      `The AI backend returned an error (${response.status}). Please try again.`,
    );
  }
  return (await response.json()) as ConsultResult;
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
