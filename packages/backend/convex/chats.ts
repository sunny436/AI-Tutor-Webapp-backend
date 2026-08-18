/**
 * chats.ts — Convex functions for the Ayurveda/Yoga chat.
 * Messages live in `consults`; each conversation has a row in `chatSessions`
 * (title + last-activity time). Everything is scoped to the logged-in user.
 */
import { getAuthUserId } from "@convex-dev/auth/server";
import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

/** Save one message and create/update its session (title + updatedAt). */
export const save = mutation({
  args: {
    sessionId: v.string(),
    role: v.string(),
    content: v.string(),
    kind: v.optional(v.string()),
    // Serialised consultation state (question cards + collected answers) so a
    // reopened chat can resume a half-finished intake. Assistant rows only.
    state: v.optional(v.string()),
  },
  handler: async (ctx, { sessionId, role, content, kind, state }) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) throw new Error("Not authenticated");
    const now = Date.now();

    await ctx.db.insert("consults", {
      userId,
      sessionId,
      role,
      content,
      kind,
      state,
      createdAt: now,
    });

    const existing = await ctx.db
      .query("chatSessions")
      .withIndex("by_user_session", (q) => q.eq("userId", userId).eq("sessionId", sessionId))
      .first();

    if (!existing) {
      await ctx.db.insert("chatSessions", {
        userId,
        sessionId,
        title: role === "user" ? content.slice(0, 60) : "New consult",
        createdAt: now,
        updatedAt: now,
      });
    } else {
      const patch: { updatedAt: number; title?: string } = { updatedAt: now };
      if (role === "user" && (!existing.title || existing.title === "New consult")) {
        patch.title = content.slice(0, 60);
      }
      await ctx.db.patch(existing._id, patch);
    }
  },
});

/** The user's conversations, newest activity first. */
export const listSessions = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return [];
    const rows = await ctx.db
      .query("chatSessions")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .collect();
    return rows.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 200);
  },
});

/** All messages of one conversation (oldest first). */
export const getMessages = query({
  args: { sessionId: v.string() },
  handler: async (ctx, { sessionId }) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return [];
    const rows = await ctx.db
      .query("consults")
      .withIndex("by_user_session", (q) => q.eq("userId", userId).eq("sessionId", sessionId))
      .collect();
    return rows.sort((a, b) => a.createdAt - b.createdAt);
  },
});

/** Rename a conversation. */
export const rename = mutation({
  args: { sessionId: v.string(), title: v.string() },
  handler: async (ctx, { sessionId, title }) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) throw new Error("Not authenticated");
    const s = await ctx.db
      .query("chatSessions")
      .withIndex("by_user_session", (q) => q.eq("userId", userId).eq("sessionId", sessionId))
      .first();
    if (s) await ctx.db.patch(s._id, { title: title.slice(0, 80) || "Untitled" });
  },
});

/** Delete a conversation and all its messages. */
export const remove = mutation({
  args: { sessionId: v.string() },
  handler: async (ctx, { sessionId }) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) throw new Error("Not authenticated");
    const s = await ctx.db
      .query("chatSessions")
      .withIndex("by_user_session", (q) => q.eq("userId", userId).eq("sessionId", sessionId))
      .first();
    if (s) await ctx.db.delete(s._id);
    const msgs = await ctx.db
      .query("consults")
      .withIndex("by_user_session", (q) => q.eq("userId", userId).eq("sessionId", sessionId))
      .collect();
    for (const m of msgs) await ctx.db.delete(m._id);
  },
});
