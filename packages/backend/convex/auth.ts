import Google from "@auth/core/providers/google";
import { Password } from "@convex-dev/auth/providers/Password";
import { convexAuth } from "@convex-dev/auth/server";
import { ConvexError, type Value } from "convex/values";
import { ResendOTP, ResendOTPReset, ResendOTPVerify } from "./authEmail";
import { normalizeEmail } from "./utils/email";

/**
 * Full auth: email+password (strength policy, mandatory email verification,
 * password reset), passwordless magic email OTP, and optional Google OAuth.
 */

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

/**
 * The single source of truth for password strength. Used by the sign-up and
 * reset flows here, by `account.setPassword`, and mirrored (as hints only) in the
 * sign-up form.
 */
export function passwordProblems(password: string): string[] {
  const problems: string[] = [];
  if (password.length < 8) problems.push("at least 8 characters");
  if (!/[a-z]/.test(password)) problems.push("a lowercase letter");
  if (!/[A-Z]/.test(password)) problems.push("an uppercase letter");
  if (!/\d/.test(password)) problems.push("a number");
  return problems;
}

export function assertPasswordAllowed(password: string): void {
  const problems = passwordProblems(password);
  if (problems.length > 0) {
    throw new ConvexError({
      code: "weak_password",
      message: `Password needs ${problems.join(", ")}.`,
    });
  }
}

const basePassword = Password({
  verify: ResendOTPVerify,
  reset: ResendOTPReset,
  validatePasswordRequirements: assertPasswordAllowed,
  // Controls the account's `providerAccountId`, so this is what makes an address
  // case-insensitive. Must match `normalizeEmail` use in `authStatus.ts`.
  profile: (params) => ({ email: normalizeEmail(params.email) }),
});

/**
 * Convex Auth's internals signal failure by throwing bare `Error`s carrying
 * sentinel strings (`InvalidSecret`, `InvalidAccountId`, `TooManyFailedAttempts`,
 * `Account … already exists`). Two problems with letting those escape:
 *
 *   1. A production Convex deployment redacts plain `Error` messages to
 *      "Server Error"; only `ConvexError` data survives.
 *   2. The Next.js auth proxy swallows *any* throw, returns a bare `null` body and
 *      clears the session cookies, so the browser only ever sees a TypeError.
 *
 * We therefore convert them to structured `ConvexError`s (useful in logs, tests,
 * and any non-proxied caller), and — for the reset flow — swallow "no such
 * account" entirely so asking to reset an unregistered address is a silent no-op
 * rather than a crash and an account-enumeration oracle.
 *
 * The forms do not rely on these errors reaching them; see `authStatus.ts`.
 */
const PasswordWithFlows = {
  ...basePassword,
  authorize: async (params: Record<string, Value | undefined>, ctx: unknown) => {
    try {
      // biome-ignore lint/suspicious/noExplicitAny: provider ctx is opaque here
      return await basePassword.authorize(params, ctx as any);
    } catch (error) {
      if (error instanceof ConvexError) throw error;
      const message = (error as Error)?.message ?? "";

      // Reset for an address with no password account: behave exactly as if a code
      // had been sent. (OTP-only users set a password from Settings instead.)
      if (params.flow === "reset" && message.includes("InvalidAccountId")) {
        return null;
      }
      if (message.includes("TooManyFailedAttempts")) {
        throw new ConvexError({ code: "rate_limited" });
      }
      if (message.includes("InvalidSecret") || message.includes("InvalidAccountId")) {
        throw new ConvexError({ code: "invalid_credentials" });
      }
      if (message.includes("already exists")) {
        throw new ConvexError({ code: "already_registered" });
      }
      if (message.includes("Could not verify code") || message.includes("Invalid code")) {
        throw new ConvexError({ code: "invalid_code" });
      }
      console.error("[auth] unexpected authorize failure:", message);
      throw new ConvexError({ code: "server_error" });
    }
  },
};

// Only offer Google once it is actually configured — otherwise the button leads
// to a guaranteed failure. Set AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET to enable.
const googleEnabled = Boolean(
  process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET,
);

export const { auth, signIn, signOut, store, isAuthenticated } = convexAuth({
  providers: [PasswordWithFlows, ResendOTP, ...(googleEnabled ? [Google] : [])],
  // Brute-force protection: a per-identifier token bucket. 5 failures, then roughly
  // one attempt returned every 12 minutes.
  signIn: { maxFailedAttempsPerHour: 5 },
  // Keep the server session in step with the 30-day "remember me" cookie set in
  // the Next.js middleware, so a cookie never outlives its session.
  session: {
    totalDurationMs: THIRTY_DAYS_MS,
    inactiveDurationMs: THIRTY_DAYS_MS,
  },
});
