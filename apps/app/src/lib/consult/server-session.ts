/**
 * Server-side session helpers for the consult routes.
 *
 * These live here rather than in `app/api/consult/route.ts` because a Next.js
 * route file may only export the handler names it recognises — POST, GET,
 * `dynamic` and friends. Exporting a helper alongside them fails the build with
 * "Property 'sessionToken' is incompatible with index signature", which is a
 * confusing way of saying "that file is not a module you may share things from".
 *
 * SERVER ONLY. `resolvePrincipal` is what makes identity trustworthy: it comes
 * from the verified session, so whatever the request body claims about who the
 * user is can be ignored.
 */

import { api } from "@v1/backend/convex/_generated/api";
import { convexAuthNextjsToken } from "@convex-dev/auth/nextjs/server";
import { ConvexHttpClient } from "convex/browser";

import type { Principal } from "./central";

/** Matches NEXT_PUBLIC_CONSULT_PROVIDER; read on the server, same value. */
export const usingCentral = process.env.NEXT_PUBLIC_CONSULT_PROVIDER === "central";

export const LOCAL_BACKEND =
  process.env.NEXT_PUBLIC_AI_BACKEND_URL ?? "http://localhost:4000";

/**
 * A live Convex token.
 *
 * Live because `middleware.ts` wraps `convexAuthNextjsMiddleware` and its
 * matcher covers `/(api|trpc)(.*)`, so the auth cookie is refreshed on the way
 * in to these routes. That is the whole reason the browser no longer carries a
 * token: `@convex-dev/auth` refreshes only when Convex's own client hits an auth
 * error, so a hand-written fetch from the page to another host kept using one
 * that had expired — the reported "AI service unavailable (401)".
 */
export async function sessionToken(): Promise<string | null> {
  return (await convexAuthNextjsToken()) ?? null;
}

/**
 * The caller's token: the cookie first, the Authorization header as a fallback.
 *
 * The cookie is preferred because the middleware refreshes it, so it is the one
 * that cannot go stale — the entire reason these calls moved server-side.
 *
 * The fallback exists because the cookie is not always readable here. Convex
 * Auth clears BOTH auth cookies whenever either one is missing or the refresh
 * call fails:
 *
 *     if (refreshToken === null || token === null) return null;   // -> cleared
 *
 * and it decides that inside the middleware, before this route ever runs. Behind
 * the tunnel — where TLS terminates at cloudflared and the app is reached over
 * plain HTTP on loopback — there are several ways to land in that branch. When
 * it happens the route sees no cookie at all and refuses a perfectly valid
 * session, which is exactly the 401 users reported.
 *
 * Falling back is not a weakening of auth. Nothing here trusts the token: the
 * Python backend verifies its signature against Convex's JWKS, and the central
 * path resolves identity by asking Convex with it. A forged one fails at both.
 * It is the same credential the browser used to send directly to the backend
 * before this route existed, verified in the same place.
 */
export function callerToken(request: Request, cookieToken: string | null): string | null {
  if (cookieToken) return cookieToken;
  const header = request.headers.get("authorization") ?? "";
  const bearer = header.replace(/^Bearer\s+/i, "").trim();
  return bearer || null;
}

/**
 * Forward a multipart request to the Python backend, carrying the session token.
 *
 * WHY THIS EXISTS
 * `uploadDocument` and `transcribeAudio` used to post straight from the browser
 * to `AI_BACKEND_URL`, which is exactly the pattern the consult route was moved
 * away from. The reason it had to move is documented at the top of
 * `app/api/consult/route.ts`: `@convex-dev/auth` refreshes a token only when
 * Convex's own client hits an auth error, so a hand-written fetch to another
 * host can carry one that expired an hour ago and nothing ever corrects it.
 *
 * These two had the same bug. It had simply not been reported, because uploads
 * are far rarer than chat turns — a tab open long enough to stale a token is
 * usually one being chatted in, not one uploading a report.
 *
 * The body is forwarded as raw BYTES with the original `content-type`. That
 * header carries the multipart boundary, so re-encoding through `formData()`
 * would produce a different boundary and a body the backend cannot parse.
 */
export async function proxyMultipart(
  request: Request,
  path: string,
  token: string,
): Promise<Response> {
  const contentType = request.headers.get("content-type") ?? "";
  const body = await request.arrayBuffer();

  const upstream = await fetch(`${LOCAL_BACKEND}${path}`, {
    method: "POST",
    headers: {
      // Never set this by hand for multipart — the boundary must survive intact.
      ...(contentType ? { "Content-Type": contentType } : {}),
      Authorization: `Bearer ${token}`,
    },
    body,
    // Transcription and OCR are slow; matches the consult route's budget.
    signal: AbortSignal.timeout(180_000),
  });

  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Who is calling, according to the session.
 *
 * Uses the existing `api.users.getUser` rather than a new Convex function, so
 * nothing has to be deployed to Convex for this to work.
 */
export async function resolvePrincipal(token: string): Promise<Principal | null> {
  const convexUrl = process.env.NEXT_PUBLIC_CONVEX_URL;
  if (!convexUrl) throw new Error("NEXT_PUBLIC_CONVEX_URL is not set");

  const client = new ConvexHttpClient(convexUrl);
  client.setAuth(token);

  const user = await client.query(api.users.getUser, {});
  if (!user?._id) return null;

  return {
    userId: String(user._id),
    email: typeof user.email === "string" ? user.email : "",
    phone: typeof user.phone === "string" ? user.phone : "",
  };
}
