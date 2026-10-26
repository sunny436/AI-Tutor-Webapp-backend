/**
 * Sending a message and streaming the reply.
 *
 * Event order (backend `app/chat/streams.py`, `app/chat/service.py`):
 *
 *   : open
 *   event: meta    — the conversation (created if new), the persisted user message,
 *                    the assistant message id. Sent after the turn is committed and
 *                    before the model starts, so it arrives almost at once.
 *   event: citations — at most one, before the first token: what [1] / [F1] point at
 *   event: token   — zero or more; a preview of the reply
 *   : keepalive    — every 15 s of silence
 *   event: done    — OR —   event: error        exactly one, then the stream ends
 *
 * `done.message` is authoritative (it may be `cancelled` after a stop). `error`
 * means the reply failed; its partial text is persisted with status `error`.
 *
 * NO SECOND REQUEST, EVER. The previous client re-sent the whole turn as a
 * non-streaming request whenever the stream ended without a final event, which
 * could run the model twice and duplicate every backend side effect. A stream that
 * ends early is reported as `interrupted`; the caller shows what arrived and may
 * re-read the persisted conversation, which is a read, not a generation.
 */

import { ApiError, errorFromResponse, isAbortError } from "./errors";
import { callRoute, notifyUnauthorized, urlFor } from "./http";
import type { RouteKey, RouteParams } from "./routes";
import { type SseEvent, SseParser } from "./sse";
import type {
  AssessmentResponse,
  AssessmentResponseRequest,
  CancelResult,
  ChatRequest,
  Feedback,
  FeedbackRating,
  StreamDone,
  StreamFailure,
  StreamMeta,
  StreamCitations,
  StreamExpression,
  StreamSpeech,
  StreamToken,
} from "./types";

export type StreamHandlers = {
  onMeta?: (meta: StreamMeta) => void;
  onToken?: (token: StreamToken) => void;
  onCitations?: (citations: StreamCitations) => void;
  onExpression?: (expression: StreamExpression) => void;
  onSpeech?: (speech: StreamSpeech) => void;
  onDone?: (done: StreamDone) => void;
  onError?: (failure: StreamFailure) => void;
};

/**
 *   done         the reply finished (possibly cancelled) — `onDone` was called
 *   error        the reply failed — `onError` was called
 *   interrupted  the stream ended before either; nothing else was sent
 *   aborted      the caller aborted the request
 */
export type StreamOutcome = "done" | "error" | "interrupted" | "aborted";

type StreamOptions = {
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
};

function parseJson<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T;
  } catch {
    return null;
  }
}

async function openStream(
  key: RouteKey,
  params: RouteParams,
  body: unknown,
  handlers: StreamHandlers,
  options: StreamOptions,
): Promise<StreamOutcome> {
  const fetcher = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetcher(urlFor(key, { params }), {
      method: "POST",
      headers:
        body === undefined
          ? { Accept: "text/event-stream" }
          : { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error) || options.signal?.aborted) return "aborted";
    throw new ApiError(0, "network_error");
  }

  // 401 / 404 / 409 / 413 / 422 / 429 / 503 all arrive before the stream opens.
  if (!response.ok) {
    const error = await errorFromResponse(response);
    notifyUnauthorized(error);
    throw error;
  }
  const type = response.headers.get("content-type") ?? "";
  if (!response.body || !type.includes("text/event-stream")) {
    throw new ApiError(response.status, "service_unavailable");
  }

  let terminal: "done" | "error" | null = null;

  const handle = ({ event, data }: SseEvent) => {
    if (terminal) return; // nothing is meaningful after the final event
    switch (event) {
      case "meta": {
        const meta = parseJson<StreamMeta>(data);
        if (meta?.conversationId && meta.assistantMessageId) handlers.onMeta?.(meta);
        return;
      }
      case "token": {
        const token = parseJson<StreamToken>(data);
        if (typeof token?.text === "string" && token.text) handlers.onToken?.(token);
        return;
      }
      case "citations": {
        const found = parseJson<StreamCitations>(data);
        if (found?.messageId && Array.isArray(found.citations)) handlers.onCitations?.(found);
        return;
      }
      case "expression": {
        const found = parseJson<StreamExpression>(data);
        if (found?.messageId && typeof found.expression === "string") handlers.onExpression?.(found);
        return;
      }
      case "speech": {
        const found = parseJson<StreamSpeech>(data);
        if (found?.messageId && typeof found.state === "string") handlers.onSpeech?.(found);
        return;
      }
      case "done": {
        const done = parseJson<StreamDone>(data);
        if (done?.message?.id) {
          terminal = "done";
          handlers.onDone?.(done);
        }
        return;
      }
      case "error": {
        const failure = parseJson<StreamFailure>(data);
        if (failure && typeof failure.code === "string") {
          terminal = "error";
          handlers.onError?.(failure);
        }
        return;
      }
      default:
        // Unknown events (e.g. future citations) must be ignored — contract rule.
        return;
    }
  };

  const parser = new SseParser(handle);
  const decoder = new TextDecoder("utf-8");
  const reader = response.body.getReader();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
      if (terminal) break;
    }
  } catch (error) {
    if (isAbortError(error) || options.signal?.aborted) return terminal ?? "aborted";
    // A dropped connection mid-stream: report it, do not retry.
    return terminal ?? "interrupted";
  } finally {
    try {
      await reader.cancel();
    } catch {
      // already closed
    }
  }

  if (!terminal) {
    parser.push(decoder.decode());
    const leftover = parser.end();
    // The final frame lost its blank line. Accept it only if it is a complete
    // terminal event; a truncated frame is not something to act on.
    if (leftover && (leftover.event === "done" || leftover.event === "error")) handle(leftover);
  }
  return terminal ?? (options.signal?.aborted ? "aborted" : "interrupted");
}

/** Send a message. No `conversationId` → the server creates the conversation. */
export function streamChat(
  request: ChatRequest,
  handlers: StreamHandlers,
  options: StreamOptions = {},
): Promise<StreamOutcome> {
  const body: ChatRequest = request.conversationId
    ? { conversationId: request.conversationId, message: request.message }
    : { message: request.message };
  if (request.attachmentIds?.length) body.attachmentIds = request.attachmentIds;
  return openStream("POST /v1/chat/stream", {}, body, handlers, options);
}

/** Replace the last reply of a conversation with a new one. */
export function streamRegenerate(
  conversationId: string,
  handlers: StreamHandlers,
  options: StreamOptions = {},
): Promise<StreamOutcome> {
  return openStream(
    "POST /v1/conversations/{conversation_id}/regenerate/stream",
    { conversation_id: conversationId },
    undefined,
    handlers,
    options,
  );
}

/**
 * Stop a reply. Idempotent. The open stream then ends with `done` whose message
 * has status `cancelled` — keep reading it to get the persisted partial text.
 */
export function cancelMessage(messageId: string, fetchImpl?: typeof fetch): Promise<CancelResult> {
  return callRoute<CancelResult>("POST /v1/messages/{message_id}/cancel", {
    params: { message_id: messageId },
    fetchImpl,
  });
}

export function setFeedback(messageId: string, rating: FeedbackRating): Promise<Feedback> {
  return callRoute<Feedback>("PUT /v1/messages/{message_id}/feedback", {
    params: { message_id: messageId },
    body: { rating },
  });
}

export function clearFeedback(messageId: string): Promise<void> {
  return callRoute<void>("DELETE /v1/messages/{message_id}/feedback", {
    params: { message_id: messageId },
  });
}

/**
 * Answer or skip the waiting question of a reply's practice test; returns the test as recorded
 * (with `learning` when the answer made its day a learning day). Sending the same response again is
 * a safe retry (the same test back). 409: the test moved on (another tab, an earlier tap) or was
 * replaced; re-read the conversation.
 */
export function respondToAssessment(messageId: string, request: AssessmentResponseRequest): Promise<AssessmentResponse> {
  return callRoute<AssessmentResponse>("POST /v1/messages/{message_id}/assessment-responses", {
    params: { message_id: messageId },
    body: request,
  });
}
