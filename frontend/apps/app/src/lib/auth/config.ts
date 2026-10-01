/**
 * Better Auth (1.7.7, pinned) for PadhAI: signing up and in, Google, email codes, password
 * reset and change, and the session lifecycle. The API (FastAPI) still checks every request
 * itself, against the same PostgreSQL tables (backend/alembic/versions/0012_better_auth.py):
 * user -> users, session -> auth_sessions, account -> auth_accounts,
 * verification -> auth_verifications. Pure (no Next.js imports): `server.ts` builds it once.
 *
 * Choices that matter for security (docs/architecture.md, "Identity"):
 * - Sign-up is email first: a code proves the address (`/sign-in/email-otp` creates the account,
 *   already verified), then the student sets a password. No account ever holds a password before
 *   its address is proven, so nobody can pre-register someone else's address.
 * - Every route this app does not use is unreachable (ROUTES in routes.ts, and disabledPaths).
 * - Per-account limits (guard.ts) on every password and code check, and per-address limits on
 *   every code sent, at the one place each code passes (sendVerificationOTP).
 * - The session cookie is `__Host-` (Secure, host-only, path /): this zone is shared with other
 *   sites, so no sibling subdomain can plant or overwrite it.
 * - Google's tokens are never stored (only the identity is used), and a Google address Google
 *   itself has not verified gets no session.
 */

import { betterAuth } from "better-auth";
import { APIError, createAuthMiddleware, getSessionFromCtx } from "better-auth/api";
import { emailOTP } from "better-auth/plugins/email-otp";
import { Pool } from "pg";

import { PLAIN_COOKIE, SECURE_COOKIE } from "@/lib/server/cookies";
import { type InternalApi, postInternal } from "./events";
import { CODE_CHECKS, CODE_SENDS, type Limit, SIGNIN, reserve } from "./guard";
import { hashPassword, verifyPassword } from "./password";
import { DISABLED_PATHS } from "./routes";

export type AuthEnv = {
  databaseUrl: string;
  secret: string;
  /** The public origin, e.g. https://ayur.namahos.com: Better Auth's baseURL and only trusted origin. */
  siteUrl: string;
  apiBaseUrl: string;
  internalToken: string;
  google: { clientId: string; clientSecret: string } | null;
  /** Off only for the e2e suite, whose requests all come from one address with no client IP. */
  rateLimit: boolean;
};

export const SESSION_DAYS = 30;
export const CODE_MINUTES = 15;
const NAME_MAX = 80;
const USER_AGENT_MAX = 300;

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
  return {
    databaseUrl: need("AUTH_DATABASE_URL"),
    secret,
    siteUrl: (env.NEXT_PUBLIC_SITE_URL?.trim() || "http://127.0.0.1:3000").replace(/\/+$/, ""),
    apiBaseUrl: (env.API_BASE_URL?.trim() || "http://127.0.0.1:4000").replace(/\/+$/, ""),
    internalToken,
    google: clientId && clientSecret ? { clientId, clientSecret } : null,
    rateLimit: env.AUTH_RATE_LIMIT !== "off",
  };
}

function bodyEmail(body: unknown): string | null {
  const email = (body as { email?: unknown } | undefined)?.email;
  return typeof email === "string" && email.includes("@") ? email.trim().toLowerCase() : null;
}

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
      freshAge: 15 * 60,
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
      // Implicit linking only between verified addresses (Better Auth's default; Google is not
      // "trusted" past its own email_verified), never to more than one address.
      accountLinking: { enabled: true, requireLocalEmailVerified: true, allowDifferentEmails: false },
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
    ],
    hooks: {
      before: createAuthMiddleware(async (ctx) => {
        switch (ctx.path) {
          case "/sign-in/email":
            await limitOrThrow(SIGNIN, bodyEmail(ctx.body));
            return;
          case "/sign-in/email-otp":
          case "/email-otp/reset-password":
            await limitOrThrow(CODE_CHECKS, bodyEmail(ctx.body));
            return;
          case "/email-otp/send-verification-otp":
            // A code here only ever signs in (or creates an account); a reset code is asked
            // for at /email-otp/request-password-reset.
            if ((ctx.body as { type?: unknown } | undefined)?.type !== "sign-in") {
              throw new APIError("BAD_REQUEST", { message: "Unsupported code type." });
            }
            return;
          case "/change-password": {
            const session = await getSessionFromCtx(ctx);
            await limitOrThrow(SIGNIN, session?.user.email ?? null);
            // Every other device is signed out when the password changes, whatever the client asked.
            return { context: { body: { ...(ctx.body as object), revokeOtherSessions: true } } };
          }
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
          after: async (session) => {
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
