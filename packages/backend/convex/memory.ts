import { v } from "convex/values";
import { internalQuery } from "./_generated/server";

/**
 * Long-term conversation memory, read by the Python AI backend.
 *
 * The data already existed — `chats.save` writes every turn into `consults` —
 * but nothing could read it back across sessions, so the assistant met every
 * user as a stranger each time they opened a new chat.
 *
 * WHY `internalQuery` AND NOT `query`
 * This is never called by a browser. It is reached only through the
 * service-key-guarded HTTP route in `http.ts`, which supplies the user id from
 * the Python side's *verified* Convex JWT. A public query taking a `userId`
 * argument would let any authenticated user read any other user's medical
 * conversations by changing one field — the exact cross-tenant hole the rest of
 * this codebase is careful about.
 */

/** How many past turns to consider. Bounded so a long-running account cannot
 *  turn one consultation into an unbounded read. */
const SCAN_LIMIT = 60;
/** How many to actually hand back. Small on purpose: this becomes prompt text,
 *  and older turns are usually noise rather than context. */
const RETURN_LIMIT = 12;

export const recentTurns = internalQuery({
  args: {
    userId: v.id("users"),
    // Excluding the live session keeps memory to what happened BEFORE now; the
    // current conversation is already threaded through the request context.
    excludeSessionId: v.optional(v.string()),
  },
  handler: async (ctx, { userId, excludeSessionId }) => {
    const rows = await ctx.db
      .query("consults")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .order("desc")
      .take(SCAN_LIMIT);

    return rows
      .filter((r) => !excludeSessionId || r.sessionId !== excludeSessionId)
      .slice(0, RETURN_LIMIT)
      .map((r) => ({
        sessionId: r.sessionId,
        role: r.role,
        // Bounded: a pasted wall of text must not blow up the AI prompt.
        content: (r.content ?? "").slice(0, 1500),
        kind: r.kind,
        createdAt: r.createdAt,
      }));
    // `state` is deliberately NOT returned — it is intake bookkeeping for
    // re-rendering question cards, not something the model should read back.
  },
});
