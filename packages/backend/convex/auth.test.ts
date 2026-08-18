/// <reference types="vite/client" />
import { convexTest } from "convex-test";
import { describe, expect, test } from "vitest";
import { api, internal } from "./_generated/api";
import { passwordProblems } from "./auth";
import schema from "./schema";
import { isValidEmail, normalizeEmail } from "./utils/email";

// Discover function modules for convex-test (includes _generated, excludes *.test.ts).
const modules = import.meta.glob(["./**/*.*s", "!./**/*.test.*"]);

const as = (userId: string) => ({ subject: `${userId}|sess_${userId}` });

/**
 * Create a password account the way Convex Auth does, so the auth surface can be
 * tested without driving the whole sign-in action (which needs SITE_URL, a mail
 * provider and real crypto).
 */
async function seedPasswordUser(
  t: ReturnType<typeof convexTest>,
  email: string,
  { verified = true } = {},
) {
  return t.run(async (ctx) => {
    const userId = await ctx.db.insert("users", {
      email,
      ...(verified ? { emailVerificationTime: Date.now() } : {}),
    });
    const accountId = await ctx.db.insert("authAccounts", {
      userId,
      provider: "password",
      providerAccountId: email,
      secret: "scrypt-hash-placeholder",
      ...(verified ? { emailVerified: email } : {}),
      // biome-ignore lint/suspicious/noExplicitAny: authTables fields vary by version
    } as any);
    const sessionId = await ctx.db.insert("authSessions", {
      userId,
      expirationTime: Date.now() + 60_000,
    });
    await ctx.db.insert("authRefreshTokens", {
      sessionId,
      expirationTime: Date.now() + 60_000,
      // biome-ignore lint/suspicious/noExplicitAny: authTables fields vary by version
    } as any);
    await ctx.db.insert("authVerificationCodes", {
      accountId,
      provider: "verify-otp",
      code: "hashed-code",
      expirationTime: Date.now() + 60_000,
      // biome-ignore lint/suspicious/noExplicitAny: authTables fields vary by version
    } as any);
    await ctx.db.insert("authRateLimits", {
      identifier: email,
      attemptsLeft: 2,
      lastAttemptTime: Date.now(),
    });
    return { userId, accountId, sessionId };
  });
}

describe("password policy (single source of truth for every flow)", () => {
  test("rejects passwords missing any required class", () => {
    expect(passwordProblems("short")).toContain("at least 8 characters");
    expect(passwordProblems("alllowercase1")).toContain("an uppercase letter");
    expect(passwordProblems("ALLUPPERCASE1")).toContain("a lowercase letter");
    expect(passwordProblems("NoDigitsHere")).toContain("a number");
  });

  test("accepts a compliant password", () => {
    expect(passwordProblems("TestUser#2026")).toEqual([]);
  });
});

describe("email canonicalisation", () => {
  // Account ids are the raw email string, so without this "Foo@X.com" and
  // "foo@x.com" become two different accounts and sign-in fails with InvalidAccountId.
  test("normalises case and surrounding space", () => {
    expect(normalizeEmail("  Foo@Example.COM ")).toBe("foo@example.com");
    expect(normalizeEmail(undefined)).toBe("");
  });

  test("accepts real addresses and rejects malformed ones", () => {
    expect(isValidEmail("a.b+tag@sub.example.co.uk")).toBe(true);
    expect(isValidEmail("no-at-sign")).toBe(false);
    expect(isValidEmail("spaces @example.com")).toBe(false);
  });
});

describe("pre-flight checks never throw and never leak account existence", () => {
  test("sign-in on an unknown address reports invalid credentials, not 'no account'", async () => {
    const t = convexTest(schema, modules);
    const result = await t.action(api.authStatus.preflightSignIn, {
      email: `nobody-${Date.now()}@example.com`,
      password: "TestUser#2026",
    });
    expect(result.ok).toBe(false);
    // Must be indistinguishable from a wrong password.
    expect(result.reason).toBe("invalid_credentials");
  });

  test("sign-up reports a free address as available", async () => {
    const t = convexTest(schema, modules);
    const result = await t.action(api.authStatus.preflightSignUp, {
      email: `fresh-${Date.now()}@example.com`,
    });
    expect(result).toEqual({ ok: true });
  });

  test("reset on an unknown address resolves quietly instead of throwing", async () => {
    const t = convexTest(schema, modules);
    // The old behaviour threw Error("InvalidAccountId") straight at the user.
    const result = await t.action(api.authStatus.preflightReset, {
      email: `nobody-${Date.now()}@example.com`,
    });
    expect(result).toEqual({ send: false });
  });

  test("pre-flight is case-insensitive about the address", async () => {
    const t = convexTest(schema, modules);
    const email = `Mixed-${Date.now()}@Example.COM`;
    await seedPasswordUser(t, normalizeEmail(email));
    const result = await t.action(api.authStatus.preflightSignUp, { email });
    expect(result.ok).toBe(false);
    expect(result.reason).toBe("already_registered");
  });
});

describe("account security summary", () => {
  test("reports password presence and verification state", async () => {
    const t = convexTest(schema, modules);
    const email = `sec-${Date.now()}@example.com`;
    const { userId } = await seedPasswordUser(t, email);
    const summary = await t
      .withIdentity(as(userId))
      .query(api.account.security, {});
    expect(summary).toMatchObject({
      email,
      emailVerified: true,
      hasPassword: true,
    });
  });

  test("returns null when unauthenticated", async () => {
    const t = convexTest(schema, modules);
    expect(await t.query(api.account.security, {})).toBeNull();
  });
});

describe("username updates", () => {
  test("throws when unauthenticated instead of silently doing nothing", async () => {
    const t = convexTest(schema, modules);
    // Previously this returned early, so onboarding reported success and saved nothing.
    await expect(t.mutation(api.users.updateUsername, { username: "someone" })).rejects.toThrow();
  });

  test("rejects an invalid username", async () => {
    const t = convexTest(schema, modules);
    const userId = await t.run((ctx) => ctx.db.insert("users", { email: "u@t.test" }));
    await expect(
      t.withIdentity(as(userId)).mutation(api.users.updateUsername, { username: "no" }),
    ).rejects.toThrow();
  });

  test("stores a valid username", async () => {
    const t = convexTest(schema, modules);
    const userId = await t.run((ctx) => ctx.db.insert("users", { email: "u2@t.test" }));
    await t.withIdentity(as(userId)).mutation(api.users.updateUsername, { username: "Valid123" });
    const stored = await t.run(async (ctx) => (await ctx.db.get(userId))?.username);
    expect(stored).toBe("valid123"); // validator lowercases
  });
});

describe("account deletion removes every trace of auth state", () => {
  test("accounts, sessions, refresh tokens, codes and rate limits all go", async () => {
    const t = convexTest(schema, modules);
    const email = `del-${Date.now()}@example.com`;
    const { userId } = await seedPasswordUser(t, email);

    await t.mutation(internal.users.deleteUserAccount, { userId });

    const leftovers = await t.run(async (ctx) => ({
      user: await ctx.db.get(userId),
      accounts: (await ctx.db.query("authAccounts").collect()).filter(
        (a) => a.userId === userId,
      ).length,
      sessions: (await ctx.db.query("authSessions").collect()).filter(
        (s) => s.userId === userId,
      ).length,
      refreshTokens: (await ctx.db.query("authRefreshTokens").collect()).length,
      codes: (await ctx.db.query("authVerificationCodes").collect()).length,
      rateLimits: (await ctx.db.query("authRateLimits").collect()).length,
    }));

    // The old implementation only ever deleted a hard-coded "google" account, so
    // the address stayed occupied and could not be re-registered cleanly.
    expect(leftovers.user).toBeNull();
    expect(leftovers.accounts).toBe(0);
    expect(leftovers.sessions).toBe(0);
    expect(leftovers.refreshTokens).toBe(0);
    expect(leftovers.codes).toBe(0);
    expect(leftovers.rateLimits).toBe(0);
  });
});
