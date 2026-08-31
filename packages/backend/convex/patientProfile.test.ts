/// <reference types="vite/client" />
import { convexTest } from "convex-test";
import { describe, expect, test } from "vitest";
import { internal } from "./_generated/api";
import schema from "./schema";

// Discover function modules for convex-test (includes _generated, excludes *.test.ts).
const modules = import.meta.glob(["./**/*.*s", "!./**/*.test.*"]);

async function seedUsers(t: ReturnType<typeof convexTest>) {
  return t.run(async (ctx) => {
    const alice = await ctx.db.insert("users", { email: "alice@t.test" });
    const bob = await ctx.db.insert("users", { email: "bob@t.test" });
    return { alice, bob };
  });
}

const ALICE_PROFILE = JSON.stringify({
  age: "34",
  conditions: ["diabetes"],
  medications: ["metformin"],
  allergies: ["penicillin"],
});
const BOB_PROFILE = JSON.stringify({ age: "58", conditions: ["hypertension"] });

describe("patient profile storage", () => {
  test("a user with no profile reads back null, not an error", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);
    const row = await t.query(internal.patientProfile.get, { userId: alice });
    expect(row).toBeNull();
  });

  test("upsert creates, then patches the same row", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);

    const first = await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });
    expect(first.created).toBe(true);

    const second = await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: JSON.stringify({ age: "35", conditions: ["diabetes"] }),
    });
    // Not a second row — one competing version of a medical history is enough.
    expect(second.created).toBe(false);

    const rows = await t.run(async (ctx) =>
      ctx.db
        .query("patientProfiles")
        .withIndex("by_user", (q) => q.eq("userId", alice))
        .collect(),
    );
    expect(rows).toHaveLength(1);
    expect(JSON.parse(rows[0].profile).age).toBe("35");
  });

  test("the stored blob survives a round trip byte for byte", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);
    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });
    const row = await t.query(internal.patientProfile.get, { userId: alice });
    expect(row?.profile).toBe(ALICE_PROFILE);
    // The backend owns the shape; Convex must not reinterpret it.
    expect(JSON.parse(row!.profile).allergies).toEqual(["penicillin"]);
  });

  test("updatedAt moves when the profile is rewritten", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);
    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });
    const before = (await t.query(internal.patientProfile.get, { userId: alice }))!;
    await new Promise((r) => setTimeout(r, 2));
    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: BOB_PROFILE,
    });
    const after = (await t.query(internal.patientProfile.get, { userId: alice }))!;
    expect(after.updatedAt).toBeGreaterThanOrEqual(before.updatedAt);
  });
});

describe("patient profile isolation — BLOCKING", () => {
  test("user A cannot read user B's medical profile", async () => {
    const t = convexTest(schema, modules);
    const { alice, bob } = await seedUsers(t);

    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });

    // Bob has stored nothing, and must see nothing — not Alice's row.
    const bobSees = await t.query(internal.patientProfile.get, { userId: bob });
    expect(bobSees).toBeNull();

    await t.mutation(internal.patientProfile.upsert, {
      userId: bob,
      profile: BOB_PROFILE,
    });

    const aliceRow = await t.query(internal.patientProfile.get, { userId: alice });
    const bobRow = await t.query(internal.patientProfile.get, { userId: bob });

    expect(aliceRow?.profile).toBe(ALICE_PROFILE);
    expect(bobRow?.profile).toBe(BOB_PROFILE);
    // The specific leak that matters: one person's diagnosis appearing in
    // another person's consultation.
    expect(bobRow?.profile).not.toContain("diabetes");
    expect(bobRow?.profile).not.toContain("penicillin");
    expect(aliceRow?.profile).not.toContain("hypertension");
  });

  test("writing as B never overwrites A's row", async () => {
    const t = convexTest(schema, modules);
    const { alice, bob } = await seedUsers(t);

    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });
    await t.mutation(internal.patientProfile.upsert, {
      userId: bob,
      profile: BOB_PROFILE,
    });

    const rows = await t.run(async (ctx) => ctx.db.query("patientProfiles").collect());
    expect(rows).toHaveLength(2);
    expect(new Set(rows.map((r) => r.userId)).size).toBe(2);

    // Alice's history is untouched by anything Bob did.
    const aliceRow = await t.query(internal.patientProfile.get, { userId: alice });
    expect(aliceRow?.profile).toBe(ALICE_PROFILE);
  });

  test("a third user with no profile sees nothing at all", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);
    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });
    const carol = await t.run(async (ctx) =>
      ctx.db.insert("users", { email: "carol@t.test" }),
    );
    expect(await t.query(internal.patientProfile.get, { userId: carol })).toBeNull();
  });
});

describe("persistence across consultations", () => {
  test("the profile outlives the consults rows of one conversation", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);

    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });

    // A first conversation happens and ends.
    await t.run(async (ctx) => {
      await ctx.db.insert("consults", {
        userId: alice,
        sessionId: "sess-1",
        role: "user",
        content: "mujhe acidity hai",
        createdAt: Date.now(),
      });
    });

    // A brand-new conversation starts. The profile is still there, which is
    // the whole point: `consults` is per-session, this is per-person.
    const row = await t.query(internal.patientProfile.get, { userId: alice });
    expect(row?.profile).toBe(ALICE_PROFILE);
    expect(JSON.parse(row!.profile).conditions).toEqual(["diabetes"]);
  });

  test("reopening later still reads the same profile", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);
    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });
    // Two independent reads, as two separate sessions would do.
    const first = await t.query(internal.patientProfile.get, { userId: alice });
    const second = await t.query(internal.patientProfile.get, { userId: alice });
    expect(first?.profile).toBe(ALICE_PROFILE);
    expect(second?.profile).toBe(first?.profile);
  });

  test("a later consultation's update is what the next one reads", async () => {
    const t = convexTest(schema, modules);
    const { alice } = await seedUsers(t);
    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: ALICE_PROFILE,
    });
    // Second consultation learns something new and saves the merged result.
    const merged = JSON.stringify({
      age: "34",
      conditions: ["diabetes", "cancer"],
      medications: ["metformin"],
      allergies: ["penicillin"],
    });
    await t.mutation(internal.patientProfile.upsert, {
      userId: alice,
      profile: merged,
    });
    const row = await t.query(internal.patientProfile.get, { userId: alice });
    expect(JSON.parse(row!.profile).conditions).toEqual(["diabetes", "cancer"]);
  });
});
