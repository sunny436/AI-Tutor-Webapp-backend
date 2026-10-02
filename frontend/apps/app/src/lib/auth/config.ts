/**
 * Better Auth (1.7.7, pinned) for PadhAI: signing up and in, Google, email codes, password
 * reset and change, two-step sign-in, and the session lifecycle. The API (FastAPI) still checks
 * every request itself, against the same PostgreSQL tables (backend/alembic/versions/0012, 0013):
 * user -> users, session -> auth_sessions, account -> auth_accounts,
 * verification -> auth_verifications, twoFactor -> auth_two_factors. Pure (no Next.js imports):
 * `server.ts` builds it once.
 *
 * Choices that matter for security (docs/architecture.md, "Identity"):
 * - Sign-up is email first: a code proves the address (`/sign-in/email-otp` creates the account,
 *   already verified), then the student sets a password. No account ever holds a password before
 *   its address is proven, so nobody can pre-register someone else's address.
 * - Every route this app does not use is unreachable (ROUTES in routes.ts, and disabledPaths).
 * - Per-account limits (guard.ts) on every password and code check, and per-address limits on
 *   every code sent, at the one place each code passes (sendVerificationOTP).
 * - A CAPTCHA (Cloudflare Turnstile, verified here) is asked for once the same counters, or a
 *   network's, show an address being hammered; it never lifts a hard limit.
 * - Passwords seen in a breach (Have I Been Pwned, k-anonymity) are refused wherever one is set.
 * - Two-step sign-in (an authenticator app, recovery codes): once on, EVERY way in asks for the
 *   second step: password, email code and Google (Better Auth's plugin covers the password
 *   only; the rest is added below). Five wrong codes lock the second step for 30 minutes.
 *   Changing how the account signs in needs a sign-in in the last 15 minutes on such an account.
 * - The session cookie is `__Host-` (Secure, host-only, path /): this zone is shared with other
 *   sites, so no sibling subdomain can plant or overwrite it.
 * - Google's tokens are never stored (only the identity is used); a Google address Google itself
 *   has not verified gets no session; and Google never attaches itself to an existing account by
 *   matching its address: that is done from Settings, signed in.
 */

import { betterAuth } from "better-auth";
import { APIError, createAuthMiddleware, getSessionFromCtx } from "better-auth/api";
import { emailOTP } from "better-auth/plugins/email-otp";
import { twoFactor } from "better-auth/plugins/two-factor";
import { Pool } from "pg";

import { PLAIN_COOKIE, SECURE_COOKIE } from "@/lib/server/cookies";
import { type InternalApi, postInternal } from "./events";
import { CODE_CHECKS, CODE_SENDS, type Limit, SIGNIN, WATCH, recent, record, reserve } from "./guard";
import { hashPassword, verifyPassword } from "./password";
import { passwordBreached, turnstileOk } from "./protection";
import { DISABLED_PATHS } from "./routes";

export type AuthEnv = {
  databaseUrl: string;
  secret: string;
  /** The public origin, e.g. https://ayur.namahos.com: Better Auth's baseURL and only trusted origin. */
  siteUrl: string;
  apiBaseUrl: string;
  internalToken: string;
  google: { clientId: string; clientSecret: string } | null;
  /** Cloudflare Turnstile; unset, the adaptive CAPTCHA is off (the hard limits still hold). */
  turnstile: { siteKey: string; secretKey: string } | null;
  /** Off only for the e2e suite, whose requests all come from one address with no client IP. */
  rateLimit: boolean;
};

export const SESSION_DAYS = 30;
export const CODE_MINUTES = 15;
/** A sign-in this recent counts as confirming it's the owner (Better Auth's freshAge). */
export const FRESH_MINUTES = 15;
const NAME_MAX = 80;
const USER_AGENT_MAX = 300;
const TWO_FACTOR_COOKIE = "two_factor";
/** An authenticator code works once (NIST SP 800-63B): kept as used for longer than it is valid. */
const USED_CODE_SECONDS = 2 * 60;
const usedCode = (userId: string, code: string) => `totp-used-${userId}-${code}`;

/** Where a session is a sign-in (anything else is Better Auth renewing one for someone signed in). */
const FIRST_STEP = new Set(["/sign-in/email", "/sign-in/email-otp", "/callback/:id"]);
const SECOND_STEP = new Set(["/two-factor/verify-totp", "/two-factor/verify-backup-code"]);
/** Changing how the account signs in: on a two-step account, only within FRESH_MINUTES of signing in. */
const RECENT_SIGN_IN = new Set([
  "/change-password",
  "/two-factor/disable",
  "/two-factor/generate-backup-codes",
  "/link-social",
]);

export function readAuthEnv(env: Record<string, string | undefined> = process.env): AuthEnv {
  const need = (name: string): string => {
    const value = env[name]?.trim();
    if (!value) throw new Error(`${name} is not set (web.env); see docs/deployment.md`);
    return value;
  };
  const secret = need("BETTER_AUTH_SECRET");
  if (secret.length < 32) throw new Error("BETTER_AUTH_SECRET must be at least 32 characters");
  const internalToken = need("AUTH_INTERNAL_TOKEN");
  if (internalToken.length < 32) throw new Error("AUTH_INTERNAL_TOKEN must be at least 32 characters");
  const clientId = env.GOOGLE_CLIENT_ID?.trim();
  const clientSecret = env.GOOGLE_CLIENT_SECRET?.trim();
  const siteKey = env.TURNSTILE_SITE_KEY?.trim();
  const secretKey = env.TURNSTILE_SECRET_KEY?.trim();
  return {
    databaseUrl: need("AUTH_DATABASE_URL"),
    secret,
    siteUrl: (env.NEXT_PUBLIC_SITE_URL?.trim() || "http://127.0.0.1:3000").replace(/\/+$/, ""),
    apiBaseUrl: (env.API_BASE_URL?.trim() || "http://127.0.0.1:4000").replace(/\/+$/, ""),
    internalToken,
    google: clientId && clientSecret ? { clientId, clientSecret } : null,
    turnstile: siteKey && secretKey ? { siteKey, secretKey } : null,
    rateLimit: env.AUTH_RATE_LIMIT !== "off",
  };
}

function bodyEmail(body: unknown): string | null {
  const email = (body as { email?: unknown } | undefined)?.email;
  return typeof email === "string" && email.includes("@") ? email.trim().toLowerCase() : null;
}

function bodyField(body: unknown, field: string): unknown {
  return (body as Record<string, unknown> | undefined)?.[field];
}

/** When the CAPTCHA is asked for: a counter already at `atLeast` in the last `minutes`. */
type Watch = { scope: string; key: string | null; atLeast: number; minutes: number };

export function createAuth(env: AuthEnv) {
  const pool = new Pool({
    connectionString: env.databaseUrl,
    max: 5,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
  });
  const api: InternalApi = { apiBaseUrl: env.apiBaseUrl, token: env.internalToken };
  const https = env.siteUrl.startsWith("https://");
  const tooMany = () => new APIError("TOO_MANY_REQUESTS", { message: "Too many attempts. Try again later." });

  const limitOrThrow = async (limit: Limit, key: string | null): Promise<void> => {
    if (key && !(await reserve(pool, limit, key))) throw tooMany();
  };

  /** Ask for a CAPTCHA when any watched counter is high; verify the one sent with Cloudflare. */
  const captcha = async (headers: Headers | undefined, ip: string | null, watches: Watch[]): Promise<void> => {
    if (!env.turnstile) return;
    let needed = false;
    for (const watch of watches) {
      if (watch.key && (await recent(pool, watch.scope, watch.key, watch.minutes)) >= watch.atLeast) {
        needed = true;
        break;
      }
    }
    if (!needed) return;
    const token = headers?.get("x-captcha-response") ?? "";
    if (!token) throw new APIError("FORBIDDEN", { code: "CAPTCHA_REQUIRED", message: "Confirm you're not a robot." });
    let passed: boolean;
    try {
      passed = await turnstileOk(token, env.turnstile.secretKey, ip);
    } catch {
      console.error("[auth] captcha check unavailable");
      throw new APIError("SERVICE_UNAVAILABLE", { code: "CAPTCHA_UNAVAILABLE", message: "Try again in a minute." });
    }
    if (!passed) throw new APIError("FORBIDDEN", { code: "CAPTCHA_INVALID", message: "Confirm you're not a robot." });
  };

  /** A password seen in a breach is refused; when the check can't run, so is the change. */
  const refuseBreached = async (password: unknown): Promise<void> => {
    if (typeof password !== "string" || password.length < 8 || password.length > 128) return; // Better Auth refuses these
    let breached: boolean;
    try {
      breached = await passwordBreached(password);
    } catch {
      console.error("[auth] breached-password check unavailable");
      throw new APIError("SERVICE_UNAVAILABLE", {
        code: "PASSWORD_CHECK_UNAVAILABLE",
        message: "Try again in a minute.",
      });
    }
    if (breached) throw new APIError("BAD_REQUEST", { code: "PASSWORD_COMPROMISED", message: "Choose another password." });
  };

  const twoFactorPlugin = twoFactor({
    issuer: "PadhAI",
    // Turning it on or off needs the account's password (an account without one sets one first).
    allowPasswordless: false,
    // Stricter than the default (10 per 15 minutes): 5 wrong codes in a row lock the second step
    // for 30 minutes, across every challenge and both kinds of code.
    accountLockout: { enabled: true, maxFailedAttempts: 5, durationSeconds: 30 * 60 },
    twoFactorCookieMaxAge: 10 * 60,
    schema: {
      user: { fields: { twoFactorEnabled: "two_factor_enabled" } },
      twoFactor: {
        modelName: "auth_two_factors",
        fields: {
          secret: "secret",
          backupCodes: "backup_codes",
          userId: "user_id",
          verified: "verified",
          failedVerificationCount: "failed_verification_count",
          lockedUntil: "locked_until",
        },
      },
    },
  });
  // The plugin's "ask for the second step" after-hook, which it runs for the password only.
  const secondStep = twoFactorPlugin.hooks.after[0]!.handler;

  const auth = betterAuth({
    appName: "PadhAI",
    baseURL: env.siteUrl,
    basePath: "/api/auth",
    secret: env.secret,
    trustedOrigins: [env.siteUrl],
    database: pool,
    telemetry: { enabled: false },
    disabledPaths: DISABLED_PATHS,
    onAPIError: { errorURL: `${env.siteUrl}/login` },
    logger: {
      level: "error",
      // Codes only: Better Auth's messages can carry an address or a database error.
      log: (level, message) => console.error(`[better-auth] ${level}: ${String(message).split("\n")[0]?.slice(0, 160)}`),
    },
    user: {
      modelName: "users",
      fields: {
        name: "display_name",
        emailVerified: "email_verified",
        image: "image",
        createdAt: "created_at",
        updatedAt: "updated_at",
      },
    },
    session: {
      modelName: "auth_sessions",
      fields: {
        token: "token",
        expiresAt: "expires_at",
        ipAddress: "ip",
        userAgent: "user_agent",
        userId: "user_id",
        createdAt: "created_at",
        updatedAt: "last_seen_at",
      },
      expiresIn: SESSION_DAYS * 24 * 60 * 60,
      updateAge: 24 * 60 * 60,
      // Removing a sign-in method needs a sign-in in the last 15 minutes.
      freshAge: FRESH_MINUTES * 60,
    },
    account: {
      modelName: "auth_accounts",
      fields: {
        accountId: "account_id",
        providerId: "provider_id",
        userId: "user_id",
        accessToken: "access_token",
        refreshToken: "refresh_token",
        idToken: "id_token",
        accessTokenExpiresAt: "access_token_expires_at",
        refreshTokenExpiresAt: "refresh_token_expires_at",
        scope: "scope",
        password: "password",
        createdAt: "created_at",
        updatedAt: "updated_at",
      },
      // Google is connected to an existing account only by its owner, signed in (Settings,
      // /link-social, same address): a Google sign-in never attaches itself to an account just
      // because the addresses match (a reissued work address, a domain admin's Google account).
      accountLinking: {
        enabled: true,
        disableImplicitLinking: true,
        requireLocalEmailVerified: true,
        allowDifferentEmails: false,
      },
    },
    verification: {
      modelName: "auth_verifications",
      fields: { identifier: "identifier", value: "value", expiresAt: "expires_at", createdAt: "created_at", updatedAt: "updated_at" },
    },
    advanced: {
      database: { generateId: "uuid" },
      ipAddress: { ipAddressHeaders: ["cf-connecting-ip"] },
      // `__Host-` instead of Better Auth's `__Secure-` prefix: Better Auth would put its prefix in
      // front of any name, so its own prefixing is off and Secure is set explicitly.
      useSecureCookies: false,
      defaultCookieAttributes: { secure: https, sameSite: "lax", httpOnly: true, path: "/" },
      cookies: {
        session_token: { name: https ? SECURE_COOKIE : PLAIN_COOKIE, attributes: { secure: https } },
      },
    },
    rateLimit: {
      enabled: env.rateLimit,
      storage: "memory",
      window: 60,
      max: 120,
      // Per address per minute, sized for a classroom behind one IP; the per-account limits in
      // guard.ts are what stop guessing.
      customRules: {
        "/sign-in/email": { window: 60, max: 60 },
        "/sign-in/social": { window: 60, max: 20 },
        "/email-otp/*": { window: 60, max: 30 },
        "/sign-in/email-otp": { window: 60, max: 30 },
        "/change-password": { window: 60, max: 10 },
        "/two-factor/*": { window: 60, max: 20 },
      },
    },
    emailAndPassword: {
      enabled: true,
      disableSignUp: true, // accounts are created by an email code first (see above)
      requireEmailVerification: true,
      minPasswordLength: 8,
      maxPasswordLength: 128,
      revokeSessionsOnPasswordReset: true,
      password: { hash: hashPassword, verify: verifyPassword },
      // A reset writes the hash with a bulk update, whose after-hook gets a row count, not the
      // account (databaseHooks below): the reset has its own notice.
      onPasswordReset: async ({ user }) => {
        postInternal(api, "events", { kind: "password_reset", userId: String(user.id) });
      },
    },
    emailVerification: { sendOnSignUp: false, sendOnSignIn: false },
    socialProviders: env.google
      ? {
          google: {
            clientId: env.google.clientId,
            clientSecret: env.google.clientSecret,
            prompt: "select_account",
            requireEmailVerification: true,
            mapProfileToUser: (profile) => ({ name: (profile.name ?? "").trim().slice(0, NAME_MAX), image: undefined }),
          },
        }
      : {},
    plugins: [
      emailOTP({
        otpLength: 6,
        expiresIn: CODE_MINUTES * 60,
        allowedAttempts: 5,
        storeOTP: "hashed",
        disableSignUp: false, // a code is how an account is created
        async sendVerificationOTP({ email, otp, type }) {
          if (type !== "sign-in" && type !== "forget-password") return;
          // The one place every code passes: limit sends per address, then let the API email it.
          // Not awaited by the caller's answer either way, so an existing address and an unknown
          // one take the same time.
          void (async () => {
            try {
              for (const limit of CODE_SENDS) {
                if (!(await reserve(pool, limit, email))) {
                  console.warn("[auth] code not sent: too many for this address");
                  return;
                }
              }
              postInternal(api, "code", { email, type, otp });
            } catch (error) {
              console.error(`[auth] code send failed: ${error instanceof Error ? error.name : "error"}`);
            }
          })();
        },
      }),
      twoFactorPlugin,
      {
        id: "padhai-two-factor-everywhere",
        hooks: {
          after: [
            // An email code is a first step like a password: the same answer, then the second step.
            { matcher: (context) => context.path === "/sign-in/email-otp", handler: secondStep },
            // Google too. The plugin answers with JSON; Google's callback is a browser redirect,
            // so the answer becomes a redirect to the second step on the sign-in page.
            { matcher: (context) => context.path === "/callback/:id", handler: secondStep },
            {
              matcher: (context) => context.path === "/callback/:id",
              handler: createAuthMiddleware(async (ctx) => {
                const returned = ctx.context.returned as { twoFactorRedirect?: unknown } | null | undefined;
                if (returned && typeof returned === "object" && returned.twoFactorRedirect === true) {
                  throw ctx.redirect(`${env.siteUrl}/login?step=two-factor`);
                }
              }),
            },
            // Security notices for two-step sign-in turned on or off (the API checks the facts).
            {
              matcher: (context) => context.path === "/two-factor/verify-totp" || context.path === "/two-factor/disable",
              handler: createAuthMiddleware(async (ctx) => {
                if (ctx.context.returned instanceof APIError) return;
                const userId = ctx.context.newSession?.user.id;
                if (!userId) return;
                if (ctx.path === "/two-factor/disable") {
                  postInternal(api, "events", { kind: "two_factor_off", userId: String(userId) });
                  return;
                }
                // The code just accepted can't be used again, at this sign-in or any other.
                const code = bodyField(ctx.body, "code");
                if (typeof code === "string") {
                  await ctx.context.internalAdapter.createVerificationValue({
                    identifier: usedCode(String(userId), code),
                    value: "used",
                    expiresAt: new Date(Date.now() + USED_CODE_SECONDS * 1000),
                  });
                }
                // Turning it on is a verify-totp from someone signed in; a sign-in carries a challenge.
                const challenge = await ctx.getSignedCookie(ctx.context.createAuthCookie(TWO_FACTOR_COOKIE).name, ctx.context.secret);
                if (!challenge) postInternal(api, "events", { kind: "two_factor_on", userId: String(userId) });
              }),
            },
          ],
        },
      },
    ],
    hooks: {
      before: createAuthMiddleware(async (ctx) => {
        const ip = ctx.headers?.get("cf-connecting-ip")?.trim() || null;
        const email = bodyEmail(ctx.body);

        if (RECENT_SIGN_IN.has(ctx.path)) {
          const session = await getSessionFromCtx(ctx);
          const twoStep = (session?.user as { twoFactorEnabled?: boolean } | undefined)?.twoFactorEnabled === true;
          if (twoStep && Date.now() - new Date(session!.session.createdAt).getTime() > FRESH_MINUTES * 60 * 1000) {
            throw new APIError("FORBIDDEN", { code: "SESSION_NOT_FRESH", message: "Sign in again to confirm it's you." });
          }
        }

        switch (ctx.path) {
          case "/sign-in/email":
            await captcha(ctx.headers, ip, [
              { scope: SIGNIN.scope, key: email, atLeast: 3, minutes: SIGNIN.minutes },
              { scope: WATCH.signinIp, key: ip, atLeast: 20, minutes: 15 },
            ]);
            await limitOrThrow(SIGNIN, email);
            if (ip) await record(pool, WATCH.signinIp, ip);
            return;
          case "/sign-in/email-otp":
          case "/email-otp/reset-password":
            await captcha(ctx.headers, ip, [
              { scope: CODE_CHECKS.scope, key: email, atLeast: 5, minutes: CODE_CHECKS.minutes },
              { scope: WATCH.codeCheckIp, key: ip, atLeast: 30, minutes: 60 },
            ]);
            await limitOrThrow(CODE_CHECKS, email);
            if (ip) await record(pool, WATCH.codeCheckIp, ip);
            if (ctx.path === "/email-otp/reset-password") await refuseBreached(bodyField(ctx.body, "password"));
            return;
          case "/email-otp/send-verification-otp":
          case "/email-otp/request-password-reset":
            // A code from send-verification-otp only ever signs in (or creates an account); a
            // reset code is asked for at /email-otp/request-password-reset.
            if (ctx.path === "/email-otp/send-verification-otp" && bodyField(ctx.body, "type") !== "sign-in") {
              throw new APIError("BAD_REQUEST", { message: "Unsupported code type." });
            }
            await captcha(ctx.headers, ip, [
              { scope: WATCH.codeAskEmail, key: email, atLeast: 2, minutes: 15 },
              { scope: WATCH.codeAskIp, key: ip, atLeast: 10, minutes: 60 },
            ]);
            if (email) await record(pool, WATCH.codeAskEmail, email);
            if (ip) await record(pool, WATCH.codeAskIp, ip);
            return;
          case "/change-password": {
            const session = await getSessionFromCtx(ctx);
            await limitOrThrow(SIGNIN, session?.user.email ?? null);
            await refuseBreached(bodyField(ctx.body, "newPassword"));
            // Every other device is signed out when the password changes, whatever the client asked.
            return { context: { body: { ...(ctx.body as object), revokeOtherSessions: true } } };
          }
          case "/two-factor/verify-totp": {
            // A code just used (seen over a shoulder, or by a phishing page) is refused, even at
            // another sign-in: the user is the challenge's at sign-in, else the one signed in.
            const challenge = await ctx.getSignedCookie(ctx.context.createAuthCookie(TWO_FACTOR_COOKIE).name, ctx.context.secret);
            const userId = challenge
              ? (await ctx.context.internalAdapter.findVerificationValue(challenge))?.value
              : (await getSessionFromCtx(ctx))?.user.id;
            const code = bodyField(ctx.body, "code");
            if (userId && typeof code === "string") {
              const used = await ctx.context.internalAdapter.findVerificationValue(usedCode(String(userId), code));
              if (used && new Date(used.expiresAt).getTime() > Date.now()) {
                throw new APIError("UNAUTHORIZED", { code: "CODE_ALREADY_USED", message: "That code was just used." });
              }
            }
            // No "trust this device": the second step is asked for at every sign-in.
            return { context: { body: { ...(ctx.body as object), trustDevice: false } } };
          }
          case "/two-factor/verify-backup-code":
            return { context: { body: { ...(ctx.body as object), trustDevice: false } } };
          default:
            return;
        }
      }),
    },
    databaseHooks: {
      user: {
        create: {
          before: async (user) => ({
            data: { ...user, name: (user.name ?? "").trim().slice(0, NAME_MAX), image: null },
          }),
        },
      },
      session: {
        create: {
          before: async (session) => ({
            data: { ...session, userAgent: session.userAgent ? session.userAgent.slice(0, USER_AGENT_MAX) : session.userAgent },
          }),
          after: async (session, ctx) => {
            // Only a sign-in raises the new-device check: not a session Better Auth renews for
            // someone already signed in (password changed, two-step turned on or off).
            const path = ctx?.path ?? "";
            if (FIRST_STEP.has(path)) {
              // With two-step sign-in on, this session is dropped at once; the second step's is the sign-in.
              const { rows } = await pool.query<{ on: boolean }>("SELECT two_factor_enabled AS on FROM users WHERE id = $1", [
                session.userId,
              ]);
              if (rows[0]?.on) return;
            } else if (!SECOND_STEP.has(path) || !ctx) {
              return;
            } else if (!(await ctx.getSignedCookie(ctx.context.createAuthCookie(TWO_FACTOR_COOKIE).name, ctx.context.secret))) {
              return; // turning two-step sign-in on (no challenge): a renewed session
            }
            postInternal(api, "events", { kind: "sign_in", userId: String(session.userId), sessionId: String(session.id) });
          },
        },
      },
      account: {
        create: {
          // Only the identity is used: Google's tokens are never kept.
          before: async (account) => ({
            data: { ...account, accessToken: null, refreshToken: null, idToken: null, scope: null },
          }),
          after: async (account) => {
            if (account.providerId === "google") {
              postInternal(api, "events", { kind: "google_linked", userId: String(account.userId) });
            }
          },
        },
        update: {
          before: async (account) => ({
            data: { ...account, accessToken: null, refreshToken: null, idToken: null, scope: null },
          }),
          after: async (account) => {
            // A credential's new hash from a change (a reset is onPasswordReset above; the first
            // password is a create).
            if (account.password) postInternal(api, "events", { kind: "password_changed", userId: String(account.userId) });
          },
        },
      },
    },
  });

  return { auth, pool };
}

export type Auth = ReturnType<typeof createAuth>["auth"];
