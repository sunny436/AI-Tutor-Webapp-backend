/**
 * consults.ts — Convex functions for saving & reading the Ayurveda/Yoga chat.
 * Each message (user or assistant) is stored per logged-in user, grouped by a
 * sessionId (one conversation).
 */
import { getAuthUserId } from "@convex-dev/auth/server";
import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/** Save one message turn. */
export const save = mutation({
  args: {
    sessionId: v.string(),
    role: v.string(),
    content: v.string(),
    kind: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) throw new Error("Not authenticated");
    await ctx.db.insert("consults", {
      userId,
      sessionId: args.sessionId,
      role: args.role,
      content: args.content,
      kind: args.kind,
      createdAt: Date.now(),
    });
  },
});

/** List this user's recent messages (newest first). */
export const listMine = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return [];
    return ctx.db
      .query("consults")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .order("desc")
      .take(200);
  },
});
