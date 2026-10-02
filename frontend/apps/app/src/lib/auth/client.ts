/**
 * The browser's Better Auth client: same-origin calls to /api/auth (only the routes in routes.ts
 * exist there). It never sees a session token: the cookie is httpOnly, and the server strips
 * tokens from every answer.
 */

import { createAuthClient } from "better-auth/client";
import { emailOTPClient, twoFactorClient } from "better-auth/client/plugins";

export const authClient = createAuthClient({ basePath: "/api/auth", plugins: [emailOTPClient(), twoFactorClient()] });

/** Better Auth's error, flattened: its code (e.g. INVALID_EMAIL_OR_PASSWORD) and HTTP status. */
export type AuthFailure = { code: string; status: number };

export function failure(error: { code?: string; status?: number } | null | undefined): AuthFailure | null {
  if (!error) return null;
  return { code: error.code ?? "UNKNOWN", status: error.status ?? 0 };
}
