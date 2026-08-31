import { v } from "convex/values";
import { internalMutation, internalQuery } from "./_generated/server";

/**
 * The persistent patient profile, read and written by the Python AI backend.
 *
 * What it holds: the long-lived clinical facts a person has stated about
 * themselves — age, diagnosed conditions, current medicines, allergies,
 * surgeries. Not symptoms, and not anything the model inferred; the backend
 * writes only what the user actually said (see its `PatientProfile` model and
 * `state.merge_profile`). Without this the assistant met every returning
 * patient as a stranger and asked for their history again.
 *
 * WHY `internalQuery`/`internalMutation` AND NOT `query`/`mutation`
 * The same reason `memory.ts` gives, and it matters more here because this is
 * a single row holding someone's medical history. These are never called by a
 * browser. They are reached only through the service-key-guarded HTTP routes
 * in `http.ts`, which supply the user id from the Python side's *verified*
 * Convex JWT subject. A public function taking a `userId` argument would let
 * any authenticated user read or overwrite any other user's medical profile
 * by changing one field.
 *
 * ISOLATION IS THE `by_user` INDEX, AND NOTHING ELSE IS TRUSTED. Every read
 * and every write is scoped by `userId` at the query level, so there is no
 * path that returns or mutates a row belonging to someone else — not a filter
 * applied after the fact, which is the kind that gets dropped in a later edit.
 */

/** This user's profile as a JSON string, or null if they have none yet. */
export const get = internalQuery({
  args: { userId: v.id("users") },
  handler: async (ctx, { userId }) => {
    const row = await ctx.db
      .query("patientProfiles")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    return row ? { profile: row.profile, updatedAt: row.updatedAt } : null;
  },
});

/**
 * Replace this user's profile with `profile`.
 *
 * REPLACE, NOT MERGE, and deliberately so. The backend has already merged:
 * `state.merge_profile` is where scalars replace, lists union, and a fact is
 * dropped only on an explicit contradiction. Duplicating any of that here
 * would mean two implementations of "what happens when a patient corrects
 * their age", which is exactly how the two drift apart. Convex stores what it
 * is given.
 */
export const upsert = internalMutation({
  args: { userId: v.id("users"), profile: v.string() },
  handler: async (ctx, { userId, profile }) => {
    const existing = await ctx.db
      .query("patientProfiles")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();

    const updatedAt = Date.now();
    if (existing) {
      await ctx.db.patch(existing._id, { profile, updatedAt });
      return { created: false };
    }
    await ctx.db.insert("patientProfiles", { userId, profile, updatedAt });
    return { created: true };
  },
});
