/**
 * Which requests the middleware lets through, which it sends to sign-in.
 *
 * Middleware only GATES PAGES, and only on the presence of the session cookie —
 * it cannot tell a live session from an expired one without asking the API, and
 * it must not try. The server layout asks (`GET /v1/me`), and the API enforces
 * every request on its own; middleware is not the security boundary.
 *
 *   /api/*         never redirected: the BFF answers JSON (a 401 envelope), because
 *                  `fetch` follows redirects and would hand a caller an HTML page
 *   /login /signup always reachable; a signed-in visitor is sent on by the page itself
 *                  (the page knows whether the cookie is still valid; we do not)
 *   /unsubscribe   always reachable: an email's link must work on any device, signed in or not
 */

export const PUBLIC_PAGES = new Set(["/login", "/signup", "/unsubscribe"]);

export type GateDecision = { action: "next" } | { action: "redirect"; location: string };

export function gate(pathname: string, search: string, hasSession: boolean): GateDecision {
  if (pathname === "/api" || pathname.startsWith("/api/")) return { action: "next" };
  if (PUBLIC_PAGES.has(pathname)) return { action: "next" };
  if (hasSession) return { action: "next" };
  const target = `${pathname}${search}`;
  return {
    action: "redirect",
    location: target === "/" ? "/login" : `/login?redirect=${encodeURIComponent(target)}`,
  };
}
