/**
 * The backend routes this app is allowed to use — and nothing else.
 *
 * ONE TABLE, THREE READERS
 *
 *   - `lib/api/*` builds every browser request from a key of this table, so the
 *     compiler rejects a call to a route that is not listed.
 *   - the BFF (`app/api/v1/[...path]`) forwards a request only when it matches an
 *     entry here. Anything else is a 404: the proxy is an allowlist, not a pipe.
 *   - `routes.test.ts` checks every entry against the backend contract
 *     (`docs/openapi.json` at the repository root), so a renamed or removed backend route fails
 *     a test instead of failing in production.
 *
 * Least privilege: endpoints the UI does not use (`POST /v1/chat`, `POST
 * /v1/conversations`, `/v1/me/settings`, `GET …/feedback`) are deliberately absent.
 * Add them here when a feature needs them, not before.
 *
 * Path parameters use the backend's own names (`{conversation_id}`) so the drift
 * test can compare paths verbatim.
 */

export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export type RouteSpec = {
  /** Needs the session cookie. The BFF answers 401 itself when it is missing. */
  auth: boolean;
  /** Request body schema name in the backend contract, if the route takes one. */
  body?: string;
  /** Query parameters the BFF may forward. Everything else is dropped. */
  query?: readonly string[];
  /** Server-Sent Events response. */
  stream?: boolean;
  /**
   * What the BFF does with the session cookie (Better Auth sets it; lib/auth):
   *   clear — the session has ended; delete the cookie
   */
  session?: "clear";
  /**
   * A raw file as the request body instead of JSON: the content types the API accepts
   * and the most bytes the BFF reads (the contract's `x-max-bytes`; the API checks too).
   */
  upload?: { types: readonly string[]; maxBytes: number };
  /** The response is a file, not JSON: its content types. See the BFF's FILES note. */
  file?: { types: readonly string[] };
  /** Voice mode's speech (features/voice): its own bounded class in the BFF, never queued behind files. */
  voice?: true;
};

export const IMAGE_UPLOAD = { types: ["image/jpeg", "image/png", "image/webp"], maxBytes: 5 * 1024 * 1024 } as const;
/** File Library uploads: any supported file as raw bytes; the API checks the type by name and content. */
export const FILE_UPLOAD = { types: ["application/octet-stream"], maxBytes: 25 * 1024 * 1024 } as const;
/** A library file's own bytes, as the type it was uploaded as (the API's FILE media types). */
export const FILE_CONTENT = {
  types: [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/plain",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "image/webp",
  ],
} as const;

/** Voice mode: one utterance, as the browser's own recorder made it (the API's `x-max-bytes`). */
export const VOICE_UPLOAD = { types: ["audio/webm", "audio/mp4", "audio/wav"], maxBytes: 1024 * 1024 } as const;
/** One sentence of a reply read aloud: Ogg Opus, AAC or MP3, as the browser asked (WAV only from the e2e stack's fake provider). */
export const VOICE_SPEECH = { types: ["audio/ogg", "audio/aac", "audio/mpeg", "audio/wav"] } as const;

export const ROUTES = {
  "POST /v1/auth/logout": { auth: true, session: "clear" },
  "POST /v1/auth/sessions/revoke-others": { auth: true },
  "GET /v1/auth/sessions": { auth: true },
  "DELETE /v1/auth/sessions/{session_id}": { auth: true },

  "GET /v1/me": { auth: true },
  "PATCH /v1/me/profile": { auth: true, body: "UpdateProfileRequest" },
  "GET /v1/me/appearance": { auth: true },
  "PATCH /v1/me/appearance": { auth: true, body: "UpdateAppearanceRequest" },
  "PUT /v1/me/avatar": { auth: true, upload: IMAGE_UPLOAD },
  "DELETE /v1/me/avatar": { auth: true },
  "GET /v1/me/avatar": { auth: true, query: ["v"], file: { types: ["image/webp"] } },
  "POST /v1/me/email/change": { auth: true, body: "EmailChangeRequest" },
  "POST /v1/me/email/confirm": { auth: true, body: "EmailConfirmRequest" },
  "DELETE /v1/me": { auth: true, body: "DeleteMeRequest", session: "clear" },

  "GET /v1/catalog/academic": { auth: false },
  "GET /v1/learning/profile": { auth: true },
  "PATCH /v1/learning/profile": { auth: true, body: "UpdateLearnerProfileRequest" },
  "GET /v1/learning/subjects": { auth: true },
  "PUT /v1/learning/subjects": { auth: true, body: "ReplaceSubjectsRequest" },
  "GET /v1/learning/preferences": { auth: true },
  "PATCH /v1/learning/preferences": { auth: true, body: "UpdateLearningPreferencesRequest" },
  "POST /v1/learning/tutor-preview": { auth: true, body: "TutorPreviewRequest" },
  "POST /v1/progress/activity": { auth: true },
  "GET /v1/progress": { auth: true, query: ["days"] },
  "GET /v1/progress/streak": { auth: true },
  "GET /v1/progress/learning-days": { auth: true, query: ["from", "to"] },
  "GET /v1/progress/plan": { auth: true },
  "GET /v1/progress/mastery": { auth: true },
  "GET /v1/progress/revisions": { auth: true },
  "GET /v1/progress/mistakes": { auth: true, query: ["limit"] },
  "GET /v1/progress/practice-tests": { auth: true, query: ["limit"] },
  "GET /v1/progress/practice-topics": { auth: true },
  "GET /v1/study/session": { auth: true },
  "POST /v1/study/session": { auth: true, body: "StudyStartIn" },
  "PATCH /v1/study/session/{session_id}": { auth: true, body: "StudyContextChangeIn" },
  "POST /v1/study/session/{session_id}/pause": { auth: true, body: "StudyTransitionIn" },
  "POST /v1/study/session/{session_id}/resume": { auth: true, body: "StudyTransitionIn" },
  "POST /v1/study/session/{session_id}/end": { auth: true, body: "StudyTransitionIn" },
  "POST /v1/study/beat": { auth: true, body: "StudyBeatIn" },
  "GET /v1/study/summary": { auth: true, query: ["days"] },
  "GET /v1/study/chapters": { auth: true, query: ["subject"] },
  "GET /v1/notifications": { auth: true, query: ["limit"] },
  "POST /v1/notifications/read": { auth: true, body: "MarkReadRequest" },
  "POST /v1/notifications/clear": { auth: true },
  "GET /v1/notifications/preferences": { auth: true },
  "PATCH /v1/notifications/preferences": { auth: true, body: "UpdateNotificationPreferencesRequest" },
  "POST /v1/notifications/unsubscribe": { auth: false, body: "UnsubscribeRequest" },
  "POST /v1/support/requests": { auth: true, body: "SupportRequestIn" },

  "GET /v1/conversations": { auth: true, query: ["limit", "cursor"] },
  "GET /v1/conversations/{conversation_id}": { auth: true },
  "PATCH /v1/conversations/{conversation_id}": { auth: true, body: "RenameConversationRequest" },
  "DELETE /v1/conversations/{conversation_id}": { auth: true },
  "GET /v1/conversations/{conversation_id}/messages": { auth: true, query: ["limit", "before"] },

  "POST /v1/chat/stream": { auth: true, body: "ChatRequest", stream: true },
  "POST /v1/conversations/{conversation_id}/regenerate/stream": { auth: true, stream: true },
  "POST /v1/messages/{message_id}/cancel": { auth: true },
  "PUT /v1/messages/{message_id}/feedback": { auth: true, body: "FeedbackRequest" },
  "DELETE /v1/messages/{message_id}/feedback": { auth: true },
  "POST /v1/messages/{message_id}/assessment-responses": { auth: true, body: "AssessmentResponseRequest" },

  "GET /v1/files": { auth: true, query: ["sha256"] },
  "POST /v1/files": { auth: true, query: ["filename"], upload: FILE_UPLOAD },
  "GET /v1/files/{file_id}": { auth: true },
  "GET /v1/files/{file_id}/content": { auth: true, file: FILE_CONTENT },
  "POST /v1/files/{file_id}/retry": { auth: true },
  "DELETE /v1/files/{file_id}": { auth: true },

  "GET /v1/voice": { auth: true },
  "POST /v1/voice/transcriptions": { auth: true, query: ["seconds"], upload: VOICE_UPLOAD, voice: true },
  "POST /v1/voice/speech": { auth: true, body: "SpeechRequest", file: VOICE_SPEECH, voice: true },
} as const satisfies Record<string, RouteSpec>;

export type RouteKey = keyof typeof ROUTES;

export type RouteParams = Record<string, string>;

/** `"GET /v1/me"` → `{ method: "GET", pattern: "/v1/me" }`. */
export function splitRouteKey(key: RouteKey): { method: HttpMethod; pattern: string } {
  const space = key.indexOf(" ");
  return { method: key.slice(0, space) as HttpMethod, pattern: key.slice(space + 1) };
}

const PARAM = /\{([a-z_]+)\}/g;

/** Backend ids are UUIDs (the contract types them `format: uuid`). */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID.test(value);
}

/**
 * Fill a route pattern: `/v1/conversations/{conversation_id}` + `{conversation_id}`.
 * Throws on a missing or non-UUID id rather than sending a request that can only fail.
 */
export function buildPath(key: RouteKey, params: RouteParams = {}): string {
  const { pattern } = splitRouteKey(key);
  return pattern.replace(PARAM, (_, name: string) => {
    const value = params[name];
    if (!value || !isUuid(value)) {
      throw new Error(`Invalid "${name}" for ${key}`);
    }
    return encodeURIComponent(value);
  });
}

/**
 * Find the route for an incoming `method` + `path` (the BFF's allowlist check).
 * `path` is the backend path, e.g. `/v1/conversations/<uuid>/messages`.
 */
export function matchRoute(
  method: string,
  path: string,
): { key: RouteKey; spec: RouteSpec; params: RouteParams } | null {
  const segments = path.split("/");
  for (const key of Object.keys(ROUTES) as RouteKey[]) {
    const { method: routeMethod, pattern } = splitRouteKey(key);
    if (routeMethod !== method) continue;
    const parts = pattern.split("/");
    if (parts.length !== segments.length) continue;

    const params: RouteParams = {};
    let ok = true;
    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index] ?? "";
      const segment = segments[index] ?? "";
      const name = /^\{([a-z_]+)\}$/.exec(part)?.[1];
      if (name) {
        if (!isUuid(segment)) {
          ok = false;
          break;
        }
        params[name] = segment;
      } else if (part !== segment) {
        ok = false;
        break;
      }
    }
    if (ok) return { key, spec: ROUTES[key], params };
  }
  return null;
}
