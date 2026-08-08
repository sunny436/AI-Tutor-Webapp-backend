import {
  convexAuthNextjsMiddleware,
  createRouteMatcher,
  nextjsMiddlewareRedirect,
} from "@convex-dev/auth/nextjs/server";
import { type NextRequest, NextResponse } from "next/server";
import { createI18nMiddleware } from "next-international/middleware";

const I18nMiddleware = createI18nMiddleware({
  locales: ["en", "fr", "es"],
  defaultLocale: "en",
  urlMappingStrategy: "rewrite",
});

/** Everything except these requires a session. */
const isPublicPage = createRouteMatcher(["/login"]);

const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

async function handler(
  request: NextRequest,
  { convexAuth }: { convexAuth: { isAuthenticated: () => Promise<boolean> } },
) {
  const isAuthenticated = await convexAuth.isAuthenticated();
  const isPublic = isPublicPage(request);

  if (isPublic && isAuthenticated) {
    return nextjsMiddlewareRedirect(request, "/");
  }

  if (!isPublic && !isAuthenticated) {
    // Preserve where they were heading so sign-in can return them there, instead
    // of dumping everyone on the dashboard.
    const url = request.nextUrl.clone();
    const target = `${request.nextUrl.pathname}${request.nextUrl.search}`;
    url.pathname = "/login";
    url.search = target && target !== "/" ? `?redirect=${encodeURIComponent(target)}` : "";
    return NextResponse.redirect(url);
  }

  return I18nMiddleware(request);
}

/**
 * "Remember me" is per-user, but Convex Auth takes the cookie lifetime as a
 * middleware-level option. It reads `options.cookieConfig` on every request
 * (inside the returned closure), so two pre-built middlewares can be selected per
 * request from a non-sensitive preference cookie set by the login form.
 *
 * Without this the library defaults to `{ maxAge: null }`, which emits the auth
 * cookies with no Max-Age — i.e. session cookies that die when the browser closes,
 * for everyone, with no way to opt out.
 *
 * The 30-day window matches `session.totalDurationMs` in `convex/auth.ts`, so a
 * cookie can never outlive the session it points at.
 */
const persistentAuth = convexAuthNextjsMiddleware(handler, {
  cookieConfig: { maxAge: THIRTY_DAYS_SECONDS },
});
const sessionOnlyAuth = convexAuthNextjsMiddleware(handler, {
  cookieConfig: { maxAge: null },
});

export default function middleware(
  request: NextRequest,
  event: Parameters<typeof persistentAuth>[1],
) {
  const remember = request.cookies.get("rememberMe")?.value === "1";
  return (remember ? persistentAuth : sessionOnlyAuth)(request, event);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
    // Convex Auth proxies signIn/signOut through /api/auth, so it must be matched.
    "/(api|trpc)(.*)",
  ],
};
