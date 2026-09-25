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
   * What the BFF does with the session cookie:
   *   issue — the response carries `{user, session}`; set the cookie, strip the token
   *   clear — the session has ended; delete the cookie
   */
  session?: "issue" | "clear";
  /**
   * A raw file as the request body instead of JSON: the content types the API accepts
   * and the most bytes the BFF reads (the contract's `x-max-bytes`; the API checks too).
   */
  upload?: { types: readonly string[]; maxBytes: number };
  /** The response is a file, not JSON: its content types. See the BFF's FILES note. */
  file?: { types: readonly string[] };
};

const IMAGE_UPLOAD = { types: ["image/jpeg", "image/png", "image/webp"], maxBytes: 5 * 1024 * 1024 } as const;

export const ROUTES = {
  "POST /v1/auth/signup": { auth: false, body: "SignupRequest" },
  "POST /v1/auth/verify-email": { auth: false, body: "VerifyEmailRequest", session: "issue" },
  "POST /v1/auth/login": { auth: false, body: "LoginRequest", session: "issue" },
  "POST /v1/auth/resend-code": { auth: false, body: "ResendCodeRequest" },
  "POST /v1/auth/password/forgot": { auth: false, body: "ForgotPasswordRequest" },
  "POST /v1/auth/password/reset": { auth: false, body: "ResetPasswordRequest", session: "issue" },
  "POST /v1/auth/password/change": { auth: true, body: "ChangePasswordRequest" },
  "POST /v1/auth/logout": { auth: true, session: "clear" },
  "POST /v1/auth/sessions/revoke-others": { auth: true },
  "GET /v1/auth/sessions": { auth: true },
  "DELETE /v1/auth/sessions/{session_id}": { auth: true },

  "GET /v1/me": { auth: true },
  "PATCH /v1/me": { auth: true, body: "UpdateMeRequest" },
  "PATCH /v1/me/profile": { auth: true, body: "UpdateProfileRequest" },
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
