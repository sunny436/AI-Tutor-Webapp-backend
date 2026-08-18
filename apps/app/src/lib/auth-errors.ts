/**
 * One place that turns anything auth can fail with into copy a person can act on.
 *
 * Two sources feed in:
 *  - reason codes from our own Convex functions (`authStatus.*`, `account.*`),
 *    which arrive intact because they bypass Convex Auth's Next.js proxy;
 *  - exceptions thrown by `signIn` / `signOut`.
 *
 * That second source needs care. Convex Auth's proxy catches every server-side
 * auth error, logs it server-side only, and returns a bare `null` body — which
 * makes the library's own client throw a `TypeError` while reading `.redirect`
 * off it. So a TypeError here means "the server rejected this and the reason was
 * discarded in transit", not "the app has a bug". We detect that shape and fall
 * back to the caller's contextual message rather than showing a stack-trace
 * artefact to the user.
 */

export const AUTH_MESSAGES = {
  invalid_credentials: "That email or password isn't right. Please try again.",
  unverified: "Please confirm your email first — we've sent you a code.",
  rate_limited:
    "Too many attempts. For your security, please wait a few minutes and try again.",
  already_registered:
    "An account with this email already exists. Try signing in instead.",
  weak_password:
    "Please choose a stronger password: at least 8 characters with upper case, lower case and a number.",
  invalid_code: "That code isn't valid or has expired. Request a new one.",
  current_password_required: "Please enter your current password.",
  wrong_current_password: "Your current password isn't correct.",
  password_unchanged: "Your new password must be different from the current one.",
  no_email: "Your account has no email address, so the password can't be changed.",
  unauthenticated: "Your session has expired. Please sign in again.",
  invalid_username:
    "Usernames must be 3–32 characters, letters and numbers only.",
  network: "We couldn't reach the server. Check your connection and try again.",
  server_error: "Something went wrong on our side. Please try again.",
} as const;

export type AuthReason = keyof typeof AUTH_MESSAGES;

/** Message for a reason code returned by one of our own functions. */
export function messageForReason(reason: string | undefined, fallback?: string) {
  if (reason && reason in AUTH_MESSAGES) {
    return AUTH_MESSAGES[reason as AuthReason];
  }
  return fallback ?? AUTH_MESSAGES.server_error;
}

/**
 * The proxy-swallowed-the-error signature, across engines:
 * Chrome "Cannot read properties of null (reading 'redirect')",
 * Firefox "result is null", Safari "null is not an object (evaluating …)".
 */
function isSwallowedServerError(error: unknown) {
  if (!(error instanceof TypeError)) return false;
  const message = error.message ?? "";
  return message.includes("redirect") || message.includes("null");
}

function isNetworkError(error: unknown) {
  const message = (error as Error)?.message ?? "";
  return (
    error instanceof TypeError &&
    (message.includes("fetch") || message.includes("Load failed") || message.includes("NetworkError"))
  );
}

/**
 * Turn a thrown auth error into a friendly message.
 *
 * `fallback` should describe what the user was doing ("That code isn't valid…"),
 * because for proxied `signIn` failures the real reason never reaches the browser
 * and the caller's context is the best information available.
 */
export function friendlyAuthError(error: unknown, fallback?: string): string {
  if (isNetworkError(error)) return AUTH_MESSAGES.network;
  if (isSwallowedServerError(error)) return fallback ?? AUTH_MESSAGES.server_error;

  // ConvexError carries structured data through to the client, in dev and prod.
  const data = (error as { data?: unknown })?.data;
  if (data && typeof data === "object") {
    const { code, message } = data as { code?: string; message?: string };
    if (code && code in AUTH_MESSAGES) return AUTH_MESSAGES[code as AuthReason];
    if (message) return message;
  }
  if (typeof data === "string" && data.trim()) return data;

  const message = (error as Error)?.message ?? "";
  // A production Convex deployment redacts raw Error messages to "Server Error",
  // and raw sentinels are not user-facing copy — never surface either verbatim.
  if (!message || message.includes("Server Error") || /^[A-Za-z]+$/.test(message)) {
    return fallback ?? AUTH_MESSAGES.server_error;
  }
  return fallback ?? AUTH_MESSAGES.server_error;
}

/** Client-side mirror of the server password policy in `convex/auth.ts`. */
export function passwordProblems(password: string): string[] {
  const problems: string[] = [];
  if (password.length < 8) problems.push("at least 8 characters");
  if (!/[a-z]/.test(password)) problems.push("a lowercase letter");
  if (!/[A-Z]/.test(password)) problems.push("an uppercase letter");
  if (!/\d/.test(password)) problems.push("a number");
  return problems;
}
