/**
 * Which of Better Auth's routes this app serves at /api/auth, and what leaves them. Pure, so it is
 * unit-tested directly (routes.test.ts).
 *
 * ALLOWLIST, like the BFF's for /api/v1: exactly these methods and paths reach Better Auth; any
 * other route it has (or a later version adds) is a 404 before it runs. Paths are matched as
 * plain lower-case segments only, so `//x`, `%2F`, `..` or a trailing slash never match
 * (a double-slash bypass of Better Auth's own disabledPaths was GHSA-x732-6j76-qmhm).
 * DISABLED_PATHS is the same rule inside Better Auth, a second layer.
 *
 * NO TOKENS: Better Auth puts the session token in some JSON answers (get-session, sign-in).
 * Page code must never see one (the cookie is httpOnly for a reason): withoutTokens removes
 * every `token` before an answer leaves the server.
 */

export const AUTH_BASE = "/api/auth";

export const AUTH_ROUTES: ReadonlySet<string> = new Set([
  "GET /get-session",
  "GET /callback/google",
  "GET /list-accounts",
  "POST /sign-in/email",
  "POST /sign-in/social",
  "POST /sign-out",
  "POST /email-otp/send-verification-otp",
  "POST /sign-in/email-otp",
  "POST /email-otp/request-password-reset",
  "POST /email-otp/reset-password",
  "POST /change-password",
  "POST /link-social",
  "POST /unlink-account",
  // Two-step sign-in: turning it on (then the first code), off, new recovery codes, and the
  // second step at sign-in (an authenticator code, or a recovery code).
  "POST /two-factor/enable",
  "POST /two-factor/disable",
  "POST /two-factor/generate-backup-codes",
  "POST /two-factor/verify-totp",
  "POST /two-factor/verify-backup-code",
]);

/** Better Auth routes this app never uses (its own 404, behind the allowlist). */
export const DISABLED_PATHS = [
  "/sign-up/email", // accounts are created by an email code (/sign-in/email-otp)
  "/update-user", // the profile is the API's (PATCH /v1/me/profile)
  "/change-email", // the API's, behind re-authentication (/v1/me/email/change)
  "/delete-user", // the API's, behind re-authentication (DELETE /v1/me)
  "/delete-user/callback",
  "/list-sessions", // the API's devices list masks addresses (/v1/auth/sessions)
  "/revoke-session",
  "/revoke-sessions",
  "/revoke-other-sessions",
  "/verify-password", // a password oracle without a per-account limit
  "/get-access-token", // Google's tokens are never stored
  "/refresh-token",
  "/account-info",
  "/request-password-reset", // reset is by email code (/email-otp/*)
  "/reset-password",
  "/verify-email",
  "/send-verification-email",
  "/email-otp/check-verification-otp",
  "/email-otp/verify-email",
  "/forget-password/email-otp",
  "/email-otp/request-email-change",
  "/email-otp/change-email",
  "/two-factor/get-totp-uri", // the secret is shown once, when it is turned on
  "/two-factor/send-otp", // the second step is an authenticator, not another email
  "/two-factor/verify-otp",
  "/two-factor/view-backup-codes",
];

const PATH = /^\/[a-z]+(?:-[a-z]+)*(?:\/[a-z]+(?:-[a-z]+)*)?$/;

/** "POST /sign-in/email" for an allowed request, otherwise null. */
export function authRoute(method: string, pathname: string): string | null {
  if (!pathname.startsWith(`${AUTH_BASE}/`)) return null;
  const path = pathname.slice(AUTH_BASE.length);
  if (!PATH.test(path)) return null;
  const key = `${method.toUpperCase()} ${path}`;
  return AUTH_ROUTES.has(key) ? key : null;
}

export function withoutTokens(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutTokens);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([key]) => key !== "token")
        .map(([key, item]) => [key, withoutTokens(item)]),
    );
  }
  return value;
}
