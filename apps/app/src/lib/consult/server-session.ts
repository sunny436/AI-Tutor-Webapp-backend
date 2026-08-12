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
