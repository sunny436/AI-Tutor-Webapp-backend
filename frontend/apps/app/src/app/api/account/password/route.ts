/**
 * `POST /api/account/password` {newPassword}: give an account its first password. The last step
 * of signing up (the account exists once its email code is entered), and Settings' "Set a
 * password" for an account that signs in with Google. Better Auth's setPassword is server-only
 * and refuses an account that already has one (that is a change, at /api/auth/change-password).
 *
 * It needs a sign-in in the last 15 minutes: a stolen older session cannot add a password and
 * keep the account. A password seen in a breach is refused (lib/auth/protection.ts). Every other
 * device is signed out, and an established account is told.
 */

import { APIError } from "better-auth/api";

import { postInternal } from "@/lib/auth/events";
import { passwordBreached } from "@/lib/auth/protection";
import { getAuth } from "@/lib/auth/server";
import { apiBaseUrl } from "@/lib/server/config";
import { isSameOrigin } from "@/lib/server/proxy-core";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const FRESH_MS = 15 * 60 * 1000;
const NEW_ACCOUNT_MS = 10 * 60 * 1000;

function fail(status: number, code: string): Response {
  return Response.json({ error: { code } }, { status, headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request): Promise<Response> {
  if (!isSameOrigin(request)) return fail(403, "forbidden");
  const { auth } = getAuth();
  const session = await auth.api.getSession({ headers: request.headers });
  if (!session) return fail(401, "unauthorized");
  if (Date.now() - new Date(session.session.createdAt).getTime() > FRESH_MS) return fail(409, "reauth_required");
  const body = (await request.json().catch(() => null)) as { newPassword?: unknown } | null;
  const newPassword = body?.newPassword;
  if (typeof newPassword !== "string" || newPassword.length < 8 || newPassword.length > 128) {
    return fail(422, "validation_error");
  }
  try {
    if (await passwordBreached(newPassword)) return fail(400, "password_compromised");
  } catch {
    console.error("[auth] breached-password check unavailable");
    return fail(503, "password_check_unavailable");
  }
  try {
    await auth.api.setPassword({ body: { newPassword }, headers: request.headers });
  } catch (error) {
    if (error instanceof APIError && error.statusCode === 400) return fail(409, "password_already_set");
    throw error;
  }
  await auth.api.revokeOtherSessions({ headers: request.headers });
  if (Date.now() - new Date(session.user.createdAt).getTime() > NEW_ACCOUNT_MS) {
    const token = process.env.AUTH_INTERNAL_TOKEN ?? "";
    postInternal({ apiBaseUrl: apiBaseUrl(), token }, "events", { kind: "password_changed", userId: session.user.id });
  }
  return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
}
