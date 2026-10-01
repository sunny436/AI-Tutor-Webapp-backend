/**
 * `/api/session/expired` — where a page goes when the API says the session is over.
 *
 * It re-checks before clearing anything. A plain "GET clears the cookie" route
 * would let any site sign a user out by linking to it; this one only clears the
 * cookie when the API itself answers 401 for it. If the session is actually fine
 * (a stale tab, a race), it sends the user back where they were going.
 */

import { safeRedirect } from "@/lib/safe-redirect";
import { backendGet } from "./backend";
import { clearedSessionCookies, readSessionToken } from "./cookies";
import { publicProtocol, publicUrlFor } from "./public-origin";

export async function handleSessionExpired(
  request: Request,
  deps: { apiBaseUrl: string; cookieSecret: string; fetchImpl?: typeof fetch },
): Promise<Response> {
  const https = publicProtocol(request.headers, request.url) === "https";
  const next = safeRedirect(new URL(request.url).searchParams.get("redirect"));
  const token = await readSessionToken(request.headers.get("cookie"), https, deps.cookieSecret);

  const result = await backendGet(deps.apiBaseUrl, "/v1/me", token, { fetchImpl: deps.fetchImpl });

  const headers = new Headers({ "Cache-Control": "no-store" });
  if (result.status === "ok" || result.status === "unavailable") {
    // Still signed in — or we cannot tell. Either way, do not sign anyone out.
    headers.set("Location", publicUrlFor(request.headers, request.url, next).toString());
    return new Response(null, { status: 303, headers });
  }

  for (const cookie of clearedSessionCookies(https)) headers.append("Set-Cookie", cookie);
  const login = new URLSearchParams({ reason: "expired" });
  if (next !== "/") login.set("redirect", next);
  headers.set("Location", publicUrlFor(request.headers, request.url, `/login?${login}`).toString());
  return new Response(null, { status: 303, headers });
}
