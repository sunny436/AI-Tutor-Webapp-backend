import { type NextRequest, NextResponse } from "next/server";

import { hasSessionCookie } from "@/lib/server/cookies";
import { gate } from "@/lib/server/gate";
import { publicUrlFor } from "@/lib/server/public-origin";

/**
 * Page gating only. Real authentication happens in the API on every request; the
 * app layout checks the session with `GET /v1/me`. See lib/server/gate.ts.
 *
 * Two behaviours are carried over from the previous app because each one fixed a
 * production failure behind the Cloudflare Tunnel:
 *
 *   HTTPS   forced here, gated on `cf-ray` (only Cloudflare adds it): the zone is
 *           shared with other sites, so the zone-wide switch is not an option, and
 *           `x-forwarded-proto` alone is synthesised by Next for direct local
 *           requests — redirecting on it sent localhost to https://localhost:3000.
 *   REDIRECTS are built from the forwarded host (publicUrlFor), never from
 *           `request.nextUrl`, which says localhost:3000 behind the tunnel.
 */
export function middleware(request: NextRequest) {
  if (request.headers.has("cf-ray") && request.headers.get("x-forwarded-proto") === "http") {
    const secure = publicUrlFor(request.headers, request.url, `${request.nextUrl.pathname}${request.nextUrl.search}`);
    secure.protocol = "https:";
    return NextResponse.redirect(secure, 308);
  }

  const { pathname, search } = request.nextUrl;
  const decision = gate(pathname, search, hasSessionCookie(request.headers.get("cookie")));
  if (decision.action === "redirect") {
    return NextResponse.redirect(publicUrlFor(request.headers, request.url, decision.location));
  }

  // Tell server components which page is being rendered, so a session that turns
  // out to be expired can come back here after signing in. Overwritten on every
  // request, so a client cannot supply its own.
  const headers = new Headers(request.headers);
  headers.set("x-pathname", `${pathname}${search}`);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: [
    // Everything except static assets, the app icon, robots.txt and the Sentry
    // tunnel (`/monitoring`), which must never be redirected to a sign-in page.
    "/((?!_next/static|_next/image|favicon\\.ico|icon\\.svg|robots\\.txt|monitoring|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml|css|js|woff2?)$).*)",
  ],
};
