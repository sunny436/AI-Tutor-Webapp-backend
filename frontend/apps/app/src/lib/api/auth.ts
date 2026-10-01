/**
 * Session calls the API owns. Signing up and in, codes, and password reset and change are Better
 * Auth's (lib/auth/client.ts); the BFF clears the httpOnly session cookie around these. Nothing
 * here ever sees a token.
 */

import { callRoute } from "./http";
import type { DeleteMeRequest, User } from "./types";

export function logout(): Promise<void> {
  return callRoute("POST /v1/auth/logout");
}

export function revokeOtherSessions(): Promise<void> {
  return callRoute("POST /v1/auth/sessions/revoke-others");
}

export function getMe(): Promise<User> {
  return callRoute("GET /v1/me");
}

/** Deletes the account and all of its data. The BFF clears the cookie. */
export function deleteAccount(request: DeleteMeRequest): Promise<void> {
  return callRoute("DELETE /v1/me", { body: request.password ? { password: request.password } : {} });
}
