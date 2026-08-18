/**
 * authStatus.ts — pre-flight checks for the sign-in / sign-up / reset forms.
 *
 * WHY THIS EXISTS
 * Every auth call from the browser goes through Convex Auth's Next.js proxy
 * (`POST /api/auth`). When the `auth:signIn` action throws, that proxy catches the
 * error, logs the reason to the *server* console, clears the auth cookies and
 * returns a bare `null` body — which then makes the library's own client throw
 * `TypeError: Cannot read properties of null (reading 'redirect')`.
 * So wrong-password, unknown-email, lockout and duplicate-account all reach the UI
 * as the same meaningless TypeError.
 *
 * These actions are called with the ordinary Convex client, so they bypass that
 * proxy completely. They NEVER throw — each returns a discriminated result the
 * form turns into a precise message before deciding whether to call `signIn`.
 *
 * Enumeration policy: "no account" and "wrong password" are deliberately collapsed
 * into a single `invalid_credentials` reason, and reset never reveals whether an
 * address is registered. Sign-up is the one place existence must be disclosed.
 */
import { retrieveAccount } from "@convex-dev/auth/server";
import { v } from "convex/values";
import { action } from "./_generated/server";
import { normalizeEmail } from "./utils/email";

const PROVIDER = "password";

type Lookup =
  | { tag: "ok"; emailVerified: boolean }
  | { tag: "no_account" }
  | { tag: "bad_password" }
  | { tag: "rate_limited" }
  | { tag: "error" };

/**
 * `retrieveAccount` does not return null on failure (its doc comment is wrong) —
 * it throws `Error("InvalidAccountId" | "InvalidSecret" | "TooManyFailedAttempts")`.
 * Translate those sentinels into a tagged result instead of letting them escape.
 *
 * Passing `secret` also drives the built-in token-bucket rate limiter: a failure
 * consumes an attempt, a success resets the bucket. That is what we want.
 */
async function lookup(
  // biome-ignore lint/suspicious/noExplicitAny: action ctx shape varies by generated types
  ctx: any,
  email: string,
  secret?: string,
): Promise<Lookup> {
  try {
    const result = await retrieveAccount(ctx, {
      provider: PROVIDER,
      account: secret === undefined ? { id: email } : { id: email, secret },
    });
    // `emailVerified` holds the verified address once confirmed, undefined before.
    const account = (result as { account?: { emailVerified?: unknown } })?.account;
    return { tag: "ok", emailVerified: account?.emailVerified != null };
  } catch (error) {
    const message = (error as Error)?.message ?? "";
    if (message.includes("InvalidAccountId")) return { tag: "no_account" };
    if (message.includes("InvalidSecret")) return { tag: "bad_password" };
    if (message.includes("TooManyFailedAttempts")) return { tag: "rate_limited" };
    console.error("[authStatus] unexpected lookup failure:", message);
    return { tag: "error" };
  }
}

/**
 * Can this email + password sign in right now?
 * `unverified` means the credentials are correct but the address still needs a code —
 * the caller should still call `signIn`, which sends a fresh one, then show the code step.
 */
export const preflightSignIn = action({
  args: { email: v.string(), password: v.string() },
  handler: async (
    ctx,
    { email, password },
  ): Promise<{ ok: boolean; reason?: string }> => {
    const result = await lookup(ctx, normalizeEmail(email), password);
    switch (result.tag) {
      case "ok":
        return result.emailVerified ? { ok: true } : { ok: false, reason: "unverified" };
      // Collapsed on purpose — telling these apart is an account-enumeration oracle.
      case "no_account":
      case "bad_password":
        return { ok: false, reason: "invalid_credentials" };
      case "rate_limited":
        return { ok: false, reason: "rate_limited" };
      default:
        return { ok: false, reason: "server_error" };
    }
  },
});

/** Is this email free to register? */
export const preflightSignUp = action({
  args: { email: v.string() },
  handler: async (ctx, { email }): Promise<{ ok: boolean; reason?: string }> => {
    const result = await lookup(ctx, normalizeEmail(email));
    if (result.tag === "no_account") return { ok: true };
    if (result.tag === "ok") return { ok: false, reason: "already_registered" };
    if (result.tag === "rate_limited") return { ok: false, reason: "rate_limited" };
    return { ok: false, reason: "server_error" };
  },
});

/**
 * Should we actually dispatch a reset code?
 *
 * The response is intentionally uninformative to the caller: the UI always shows
 * "if an account exists, we've sent a code" and always advances to the code step.
 * `send` only tells the client whether calling `signIn(flow:"reset")` would throw —
 * it is a crash guard, not an answer about whether the address is registered.
 *
 * Note an OTP-only user has no `password` account, so there is nothing to reset;
 * `modifyAccountCredentials` would throw for them. They set a password from
 * Settings instead (see `account.setPassword`).
 */
export const preflightReset = action({
  args: { email: v.string() },
  handler: async (ctx, { email }): Promise<{ send: boolean }> => {
    const result = await lookup(ctx, normalizeEmail(email));
    return { send: result.tag === "ok" };
  },
});
