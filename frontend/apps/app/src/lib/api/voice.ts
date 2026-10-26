/**
 * Voice mode's speech, through the web app's own proxy only: what the student said (one recorded utterance)
 * and one sentence of their reply read aloud. The API decides who voice mode is for and holds OllaLink's key;
 * nothing here ever talks to OllaLink.
 */

import { ApiError, errorFromResponse, isAbortError } from "./errors";
import { callRoute, notifyUnauthorized, urlFor } from "./http";
import type { RouteKey } from "./routes";
import type { SpeechRequest, VoiceAvailability, VoiceTranscript } from "./types";

export function getVoice(signal?: AbortSignal): Promise<VoiceAvailability> {
  return callRoute<VoiceAvailability>("GET /v1/voice", { signal });
}

async function send(key: RouteKey, init: RequestInit, query?: Record<string, string>): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(urlFor(key, { query }), { ...init, credentials: "same-origin", cache: "no-store" });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, "network_error");
  }
  if (!response.ok) {
    const error = await errorFromResponse(response);
    notifyUnauthorized(error);
    throw error;
  }
  return response;
}

/**
 * Too many at once is said before any work is done: the proxy's `busy` before it reads the request, the API's
 * `voice_busy` before it asks OllaLink. Nothing was done or billed, so that one is tried once more.
 */
async function once<T>(attempt: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  try {
    return await attempt();
  } catch (error) {
    if (!(error instanceof ApiError) || (error.code !== "busy" && error.code !== "voice_busy")) throw error;
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (signal?.aborted) throw error;
    return attempt();
  }
}

/** What was said in one recording ("" when nothing was heard). */
export function transcribe(audio: Blob, seconds: number, signal?: AbortSignal): Promise<VoiceTranscript> {
  return once(async () => {
    const response = await send(
      "POST /v1/voice/transcriptions",
      { method: "POST", headers: { "Content-Type": audio.type, Accept: "application/json" }, body: audio, signal },
      { seconds: Math.min(60, Math.max(0.1, seconds)).toFixed(2) },
    );
    return (await response.json()) as VoiceTranscript;
  }, signal);
}

/** One sentence of the student's own reply, spoken: the audio's bytes (MP3). */
export function synthesize(request: SpeechRequest, signal?: AbortSignal): Promise<ArrayBuffer> {
  return once(async () => {
    const response = await send("POST /v1/voice/speech", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "audio/ogg, audio/aac, audio/mpeg, audio/wav" },
      body: JSON.stringify(request),
      signal,
    });
    return response.arrayBuffer();
  }, signal);
}
