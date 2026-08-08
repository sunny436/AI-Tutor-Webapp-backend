/**
 * account.ts — authenticated account-security operations.
 *
 * Convex Auth's `Password` provider has no "change password" flow (it only covers
 * sign-up / sign-in / reset), so this builds one from the exported primitives.
 *
 * It also covers the gap for people who signed up with a magic code: they have a
 * `resend-otp` account but no `password` account, so `modifyAccountCredentials`
 * would throw for them and password reset can never work. Here they can *set* a
 * first password, which is what makes reset available to them afterwards.
 */
import {
  createAccount,
  getAuthSessionId,
  getAuthUserId,
  invalidateSessions,
  modifyAccountCredentials,
  retrieveAccount,
} from "@convex-dev/auth/server";
import { ConvexError, v } from "convex/values";
import { api } from "./_generated/api";
import { action, query } from "./_generated/server";
import { assertPasswordAllowed } from "./auth";
import { normalizeEmail } from "./utils/email";

const PROVIDER = "password";

/** Does the signed-in user already have a password, and is their email confirmed? */
export const security = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return null;
    const user = await ctx.db.get(userId);
    if (!user) return null;
    const accounts = await ctx.db
      .query("authAccounts")
      .withIndex("userIdAndProvider", (q) => q.eq("userId", userId))
      .collect();
    return {
      email: user.email ?? null,
      emailVerified: user.emailVerificationTime != null,
      hasPassword: accounts.some((a) => a.provider === PROVIDER),
      providers: accounts.map((a) => a.provider),
    };
  },
});

/**
 * Set or change the signed-in user's password.
 *
 * `currentPassword` is required only when one already exists — an OTP-only user has
 * nothing to prove beyond the active session. On success every *other* session is
 * invalidated, so a stolen session cannot outlive a password change.
 */
export const setPassword = action({
  args: {
    currentPassword: v.optional(v.string()),
    newPassword: v.string(),
  },
  handler: async (ctx, { currentPassword, newPassword }): Promise<{ ok: true }> => {
    const userId = await getAuthUserId(ctx);
    if (!userId) throw new ConvexError({ code: "unauthenticated" });

    const sessionId = await getAuthSessionId(ctx);
    const security = await ctx.runQuery(api.account.security, {});
    if (!security?.email) {
      throw new ConvexError({ code: "no_email" });
    }
    const email = normalizeEmail(security.email);

    assertPasswordAllowed(newPassword);

    if (security.hasPassword) {
      if (!currentPassword) {
        throw new ConvexError({ code: "current_password_required" });
      }
      // Verifying through `retrieveAccount` also feeds the shared rate limiter,
      // so this endpoint can't be used to brute-force the existing password.
      try {
        await retrieveAccount(ctx, {
          provider: PROVIDER,
          account: { id: email, secret: currentPassword },
        });
      } catch (error) {
        const message = (error as Error)?.message ?? "";
        if (message.includes("TooManyFailedAttempts")) {
          throw new ConvexError({ code: "rate_limited" });
        }
        throw new ConvexError({ code: "wrong_current_password" });
      }

      if (currentPassword === newPassword) {
        throw new ConvexError({ code: "password_unchanged" });
      }

      await modifyAccountCredentials(ctx, {
        provider: PROVIDER,
        account: { id: email, secret: newPassword },
      });
    } else {
      // First password for an OTP/OAuth-only user. `shouldLinkViaEmail` attaches it
      // to the existing user rather than creating a second one.
      await createAccount(ctx, {
        provider: PROVIDER,
        account: { id: email, secret: newPassword },
        // `emailVerified` is read by Convex Auth's account-linking step and stripped
        // before the `users` row is written, so it isn't part of the users doc type.
        profile: { email, emailVerified: security.emailVerified } as { email: string },
        shouldLinkViaEmail: true,
      });
    }

    // Keep this device signed in, drop everything else.
    await invalidateSessions(ctx, {
      userId,
      except: sessionId ? [sessionId] : [],
    });
    return { ok: true };
  },
});
