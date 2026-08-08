import { getAuthUserId } from "@convex-dev/auth/server";
import { asyncMap } from "convex-helpers";
import { ConvexError, v } from "convex/values";
import { internal } from "./_generated/api";
import { action, internalMutation, mutation, query } from "./_generated/server";
import { polar } from "./subscriptions";
import { username } from "./utils/validators";

export const getUser = query({
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) {
      return;
    }
    const user = await ctx.db.get(userId);
    if (!user) {
      return;
    }
    const subscription = await polar.getCurrentSubscription(ctx, {
      userId: user._id,
    });
    return {
      ...user,
      name: user.username || user.name,
      subscription,
      avatarUrl: user.imageId
        ? await ctx.storage.getUrl(user.imageId)
        : undefined,
    };
  },
});

export const updateUsername = mutation({
  args: {
    username: v.string(),
  },
  handler: async (ctx, args) => {
    const userId = await getAuthUserId(ctx);
    // Must throw, not return: onboarding awaits this and would otherwise report
    // success while saving nothing, leaving the user stuck behind the username gate.
    if (!userId) {
      throw new ConvexError({ code: "unauthenticated" });
    }
    const validatedUsername = username.safeParse(args.username);

    if (!validatedUsername.success) {
      throw new ConvexError({
        code: "invalid_username",
        message:
          validatedUsername.error.issues[0]?.message ??
          "Username must be 3-32 letters or numbers.",
      });
    }
    await ctx.db.patch(userId, { username: validatedUsername.data });
  },
});

export const generateUploadUrl = mutation({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) {
      throw new Error("User not found");
    }
    return await ctx.storage.generateUploadUrl();
  },
});

export const updateUserImage = mutation({
  args: {
    imageId: v.id("_storage"),
  },
  handler: async (ctx, args) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) {
      return;
    }
    ctx.db.patch(userId, { imageId: args.imageId });
  },
});

export const removeUserImage = mutation({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) {
      return;
    }
    ctx.db.patch(userId, { imageId: undefined, image: undefined });
  },
});

/**
 * Remove a user and every trace of their authentication state.
 *
 * The previous version deleted only a hard-coded `["google"]` account, so a
 * password or magic-code account (plus all sessions, refresh tokens and pending
 * verification codes) survived the delete. Those orphans kept the address
 * occupied, so re-registering the same email failed or silently re-attached to a
 * deleted user. Everything keyed to the user is now removed.
 */
export const deleteUserAccount = internalMutation({
  args: {
    userId: v.id("users"),
  },
  handler: async (ctx, args) => {
    const accounts = await ctx.db
      .query("authAccounts")
      .withIndex("userIdAndProvider", (q) => q.eq("userId", args.userId))
      .collect();

    await asyncMap(accounts, async (account) => {
      // Pending codes reference the account, and the rate-limit bucket is keyed by
      // account id (password) or email (magic code) — clear both.
      const codes = await ctx.db
        .query("authVerificationCodes")
        .withIndex("accountId", (q) => q.eq("accountId", account._id))
        .collect();
      await asyncMap(codes, (code) => ctx.db.delete(code._id));

      for (const identifier of [account._id as string, account.providerAccountId]) {
        const limit = await ctx.db
          .query("authRateLimits")
          .withIndex("identifier", (q) => q.eq("identifier", identifier))
          .unique();
        if (limit) await ctx.db.delete(limit._id);
      }

      await ctx.db.delete(account._id);
    });

    const sessions = await ctx.db
      .query("authSessions")
      .withIndex("userId", (q) => q.eq("userId", args.userId))
      .collect();

    await asyncMap(sessions, async (session) => {
      const tokens = await ctx.db
        .query("authRefreshTokens")
        .withIndex("sessionId", (q) => q.eq("sessionId", session._id))
        .collect();
      await asyncMap(tokens, (token) => ctx.db.delete(token._id));
      await ctx.db.delete(session._id);
    });

    await ctx.db.delete(args.userId);
  },
});

export const deleteCurrentUserAccount = action({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) {
      throw new ConvexError({ code: "unauthenticated" });
    }
    // Billing is optional here (Polar may not be configured at all). Never let it
    // block the deletion the user actually asked for.
    try {
      const subscription = await polar.getCurrentSubscription(ctx, { userId });
      if (subscription) {
        await polar.cancelSubscription(ctx, { revokeImmediately: true });
      }
    } catch (error) {
      console.error(
        "[users] could not cancel subscription during account deletion:",
        (error as Error)?.message,
      );
    }
    await ctx.runMutation(internal.users.deleteUserAccount, {
      userId,
    });
  },
});
