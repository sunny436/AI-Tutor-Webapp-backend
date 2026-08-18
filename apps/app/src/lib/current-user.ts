import "server-only";

import { convexAuthNextjsToken } from "@convex-dev/auth/nextjs/server";
import { api } from "@v1/backend/convex/_generated/api";
import { fetchQuery } from "convex/nextjs";

/**
 * Who is asking, on the server.
 *
 * ONE PLACE, because there are now two: `[locale]/page.tsx` chooses between the
 * marketing page and the dashboard, and `(dashboard)/layout.tsx` gates the six
 * routes inside it. Both need the same answer and must not drift apart.
 *
 * DECIDE ON THE USER, NOT ON THE TOKEN. An expired or revoked cookie still makes
 * `convexAuthNextjsToken()` return a string — only Convex knows whether it is
 * still honoured. Branching on the token's mere presence would send a
 * stale-session visitor down the dashboard path, where `getUser` returns
 * undefined, the onboarding gate fires, and they land on
 * `/login?redirect=%2Fonboarding` instead of the page they asked for.
 *
 * The early return matters for a different reason: an anonymous visitor to the
 * landing page makes ZERO Convex round trips. Without it, every crawler and
 * every first-time visitor would pay a network call to be told they are not
 * signed in.
 *
 * `getUser` itself returns `undefined` rather than throwing when unauthenticated
 * (`packages/backend/convex/users.ts:12`), which is why this can be a plain
 * `await` with no try/catch around the common case.
 */
export async function currentUser() {
  const token = await convexAuthNextjsToken();
  if (!token) return null;
  try {
    return (await fetchQuery(api.users.getUser, {}, { token })) ?? null;
  } catch {
    // A Convex outage must not take the marketing page down with it. Treating an
    // unreachable backend as "signed out" degrades `/` to the landing page,
    // which is static content and still useful, instead of a 500.
    return null;
  }
}
