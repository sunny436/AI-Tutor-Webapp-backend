/**
 * Account and session calls. The BFF sets and clears the httpOnly session cookie
 * around these; nothing here ever sees a token.
 */

import { callRoute } from "./http";
import type {
  ChangePasswordRequest,
  DeleteMeRequest,
  ForgotPasswordRequest,
  LoginRequest,
  ResendCodeRequest,
  ResetPasswordRequest,
  SignedIn,
  SignupRequest,
  User,
  VerifyEmailRequest,
} from "./types";

/** Always 202, whether or not the address can be registered (no enumeration). */
export function signup(request: SignupRequest): Promise<void> {
  const body: SignupRequest = { email: request.email, password: request.password };
  const name = request.displayName?.trim();
  if (name) body.displayName = name;
  return callRoute("POST /v1/auth/signup", { body });
}

export function verifyEmail(request: VerifyEmailRequest): Promise<SignedIn> {
  return callRoute("POST /v1/auth/verify-email", {
    body: { email: request.email, code: request.code },
  });
}

/** 403 `email_not_verified` when the address still needs its code. */
export function login(request: LoginRequest): Promise<SignedIn> {
  return callRoute("POST /v1/auth/login", {
    body: { email: request.email, password: request.password },
  });
}

/** Always 202. */
export function resendCode(request: ResendCodeRequest): Promise<void> {
  return callRoute("POST /v1/auth/resend-code", {
    body: { email: request.email, purpose: request.purpose ?? "verify_email" },
  });
}

/** Always 202. */
export function forgotPassword(request: ForgotPasswordRequest): Promise<void> {
  return callRoute("POST /v1/auth/password/forgot", { body: { email: request.email } });
}

/** Signs the user in; every other session is revoked. */
export function resetPassword(request: ResetPasswordRequest): Promise<SignedIn> {
  return callRoute("POST /v1/auth/password/reset", {
    body: { email: request.email, code: request.code, newPassword: request.newPassword },
  });
}

/** Other sessions are revoked; this one stays signed in. */
export function changePassword(request: ChangePasswordRequest): Promise<void> {
  return callRoute("POST /v1/auth/password/change", {
    body: { currentPassword: request.currentPassword, newPassword: request.newPassword },
  });
}

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
  return callRoute("DELETE /v1/me", { body: { password: request.password } });
}
