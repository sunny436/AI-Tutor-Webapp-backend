import {
  convexAuthNextjsMiddleware,
  createRouteMatcher,
} from "@convex-dev/auth/nextjs/server";
import { type NextRequest, NextResponse } from "next/server";
import { createI18nMiddleware } from "next-international/middleware";
// The locale list was written out THREE times in this file — once for
// createI18nMiddleware, once as a const, and once inside the regex on the
// redirect path. Three copies of a list that must agree.
import { DEFAULT_LOCALE, LOCALES, stripLocale } from "@/lib/locales";

/**
 * "redirect", not "rewrite" — and the reason is not cosmetic.
 *
 * With "rewrite", next-international answers `/login` with an internal rewrite
 * to `/en/login`, built as an absolute URL from `request.url`. Behind the
 * tunnel that URL reads `https://localhost:3000` — an origin this server does
 * not serve, because it speaks plain HTTP — so Next stopped treating the
 * rewrite as internal and re-entered middleware for the rewritten path. On that
 * re-entry the `Host` header was `localhost:3000`, and Convex Auth keys its
 * cookie NAMES off Host: on localhost it drops the `__Host-` prefix. It then
 * looked for `__convexAuthJWT`, the browser had sent `__Host-__convexAuthJWT`,
 * and it concluded the visitor was signed out. The result was a redirect
 * ping-pong: `/` said signed-out and sent users to `/login`, `/login` said
 * signed-in and sent them back, until the browser gave up with
 * ERR_TOO_MANY_REDIRECTS.
 *
 * A redirect has no such internal leg. It is one visible hop whose Location we
 * can correct (see `withPublicLocation`), so the browser always comes back on
 * the real hostname and every request carries its cookies.
 *
 * The visible cost is that URLs now show the locale: /en/login rather than
 * /login. That is standard for i18n sites and is the cheaper half of the trade.
 */
const I18nMiddleware = createI18nMiddleware({
  locales: [...LOCALES],
  defaultLocale: DEFAULT_LOCALE,
  urlMappingStrategy: "redirect",
});

/**
 * TWO MATCHERS, NOT ONE — and the split is what makes a public `/` safe.
 *
 * The locale-prefixed variants are NOT redundant. With
 * `urlMappingStrategy: "redirect"` the browser URL always carries the locale, so
 * by the time a second request arrives the path really is `/en/login`. Matching
 * only `/login` classified the login page itself as protected, which redirected
 * it to `/login`, which acquired the prefix again: an infinite loop that nested
 * the `redirect` parameter on every pass until the browser gave up. Nobody could
 * sign in.
 *
 * `createRouteMatcher(["/"])` is an EXACT match, not a prefix wildcard —
 * verified against the installed path-to-regexp, which compiles it to
 * `/^\/[\/#\?]?$/i`. Adding "/" here cannot accidentally make the app public.
 *
 * `/fr` and `/es` are load-bearing, not defensive padding: next-international
 * picks the locale from the `Next-Locale` cookie and then `Accept-Language`, so
 * a French-configured browser lands on `/fr`. Omit it and those visitors get the
 * login page instead of the landing page.
 */
const isAuthPage = createRouteMatcher([
  "/login",
  ...LOCALES.map((locale) => `/${locale}/login`),
]);

const isMarketingPage = createRouteMatcher(["/", ...LOCALES.map((locale) => `/${locale}`)]);

const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

/**
 * The URL the *browser* used, which is not what `request.nextUrl` reports.
 *
 * Next does not trust the Host header for `nextUrl`: behind any proxy it still
 * reports `localhost:3000`. It DOES honour `x-forwarded-proto`. Redirecting with
 * an unpatched `nextUrl.clone()` therefore sent real users to
 * `https://localhost:3000/login` — a dead address on their own machine. This is
 * a production bug in its own right, not something Cloudflare introduced; it was
 * simply invisible while the only client was a browser on this same host.
 */
function publicUrl(request: NextRequest): URL {
  const url = request.nextUrl.clone();
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const proto = request.headers.get("x-forwarded-proto");
  if (host) {
    // Assign hostname and port separately. The `host` setter ignores a missing
    // port and keeps whatever was there, so `url.host = "ayur.example.com"` left
    // the internal :3000 in place and redirected users to
    // https://ayur.example.com:3000/login — a port Cloudflare does not serve.
    const [hostname = "", port = ""] = host.split(":");
    if (hostname) {
      url.hostname = hostname;
      url.port = port;
    }
  }
  if (proto) url.protocol = `${proto}:`;
  return url;
}

/**
 * Keep a same-app rewrite internal.
 *
 * `next-international` builds its rewrite from `request.url`, which carries the
 * forwarded `https` scheme while this server actually speaks plain HTTP. Next
 * compares the two origins, decides the rewrite points somewhere external, and
 * tries to proxy to `https://localhost:3000/...` — which refuses the connection,
 * so every page rendered through the locale rewrite returned 500 behind the
 * tunnel. Forcing the scheme back to http makes the origins match again and Next
 * handles the rewrite in-process, as it does when no proxy is involved.
 */
function withPublicLocation(response: NextResponse, request: NextRequest): NextResponse {
  const location = response.headers.get("location");
  if (!location) return response;
  try {
    const target = new URL(location, request.nextUrl);
    const publicOrigin = publicUrl(request);
    // Only rewrite our own origin. An external Location — Google's OAuth screen,
    // say — must be left exactly as issued.
    if (target.host === request.nextUrl.host) {
      target.protocol = publicOrigin.protocol;
      target.hostname = publicOrigin.hostname;
      target.port = publicOrigin.port;
      response.headers.set("location", target.toString());
    }
  } catch {
    // Relative Location; the browser resolves it against the real host already.
  }
  return response;
}

async function handler(
  request: NextRequest,
  { convexAuth }: { convexAuth: { isAuthenticated: () => Promise<boolean> } },
) {
  // An API route is not a page: no locale, no redirect. Bail out before either.
  //
  // This function ends by handing the request to the i18n middleware, which
  // rewrites "/consult" to "/en/consult". Applied to "/api/consult" that
  // produces "/en/api/consult", which does not exist — a 404 on every chat
  // message, reported live as "AI service unavailable (404)".
  //
  // It only bit SIGNED-IN callers, which is exactly why the first version of
  // this shipped: an anonymous caller returned earlier, from the auth branch
  // below, and never reached the rewrite. Testing the endpoint signed out
  // therefore proved nothing about the path real users take.
  //
  // Returning here still leaves `convexAuthNextjsMiddleware` (which wraps this
  // handler) to refresh the auth cookie — the whole reason these calls go
  // through the server. Each route does its own auth check, and Convex Auth's
  // own /api/auth endpoints must stay reachable while signed out anyway.
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return;
  }

  const isAuthenticated = await convexAuth.isAuthenticated();
  // Marketing pages are public AND never redirected. That second property is the
  // one that matters: a URL that cannot redirect cannot take part in a redirect
  // cycle, which is what makes `/` safe to open up at all.
  const isPublic = isAuthPage(request) || isMarketingPage(request);

  if (isAuthPage(request) && isAuthenticated) {
    // Deliberately NOT `nextjsMiddlewareRedirect`. That helper builds its
    // Location from `request.nextUrl`, which reports localhost:3000 behind a
    // proxy — so a signed-in visitor hitting /login was sent to
    // https://localhost:3000/, an address that exists on nobody's machine. The
    // browser failed it with ERR_SSL_PROTOCOL_ERROR and sign-in appeared to
    // hang on the login page even though the session was already valid.
    const home = publicUrl(request);
    home.pathname = "/";
    home.search = "";
    return NextResponse.redirect(home);
  }

  if (!isPublic && !isAuthenticated) {
    // API routes never reach here — they returned at the top of this function —
    // so this branch only ever redirects pages. That matters: `fetch` follows
    // redirects, so a 307 to /login would hand the caller 200 OK and a page of
    // HTML to parse as JSON, and a signed-out session would look like a broken
    // app rather than "please sign in".

    // Preserve where they were heading so sign-in can return them there, instead
    // of dumping everyone on the dashboard.
    const url = publicUrl(request);
    // Strip the locale the i18n redirect has already added, so the round trip
    // records "/consult" rather than "/en/consult" — the latter is an internal
    // path that would be rewritten a second time on the way back.
    const bare = stripLocale(request.nextUrl.pathname);
    const target = `${bare}${request.nextUrl.search}`;
    url.pathname = "/login";
    url.search = target && target !== "/" ? `?redirect=${encodeURIComponent(target)}` : "";
    return NextResponse.redirect(url);
  }

  return withPublicLocation(I18nMiddleware(request) as NextResponse, request);
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
  verbose: process.env.AUTH_VERBOSE === "1",
});
const sessionOnlyAuth = convexAuthNextjsMiddleware(handler, {
  cookieConfig: { maxAge: null },
  verbose: process.env.AUTH_VERBOSE === "1",
});

export default function middleware(
  request: NextRequest,
  event: Parameters<typeof persistentAuth>[1],
) {
  // Force HTTPS, in the app rather than at the CDN.
  //
  // Cloudflare's "Always Use HTTPS" would do this too, but that switch applies
  // to the WHOLE zone, and this zone is shared with the company's main site,
  // its Vercel deployment and its mail hosts. Flipping a zone-wide switch to
  // protect one subdomain risks other people's services, so the redirect lives
  // here instead, where it can only affect this app.
  //
  // Gated on `cf-ray`, which only Cloudflare adds, because `x-forwarded-proto`
  // alone is not the signal it looks like: Next synthesises that header from the
  // connection when no proxy set it, so a direct `http://localhost:3000` request
  // also reports "http". Redirecting on that turned every local visit into
  // https://localhost:3000 — a port that speaks plain HTTP — and Chromium failed
  // it outright with ERR_SSL_PROTOCOL_ERROR. Keying on a header only the real
  // edge can produce keeps local access working and still forces HTTPS for the
  // public. 308 preserves the method and body.
  const viaCloudflare = request.headers.has("cf-ray");
  if (viaCloudflare && request.headers.get("x-forwarded-proto") === "http") {
    const secure = publicUrl(request);
    secure.protocol = "https:";
    return NextResponse.redirect(secure, 308);
  }

  const remember = request.cookies.get("rememberMe")?.value === "1";
  return (remember ? persistentAuth : sessionOnlyAuth)(request, event);
}

export const config = {
  matcher: [
    // `robots.txt`, `sitemap.xml` and `monitoring` are excluded, and each for a
    // reason that was already costing something:
    //
    //   robots/sitemap — the old lookahead excluded image extensions but not
    //     .txt/.xml, so a crawler asking for /robots.txt was answered with a 307
    //     to /login. Note they must be excluded from the MATCHER, not added to
    //     `isMarketingPage`: doing the latter lets them fall through to the i18n
    //     middleware, which would send /robots.txt to /en/robots.txt and a 404 —
    //     the identical failure mode to the /api/ outage this file documents.
    //
    //   monitoring — `next.config.mjs` sets `tunnelRoute: "/monitoring"` for
    //     Sentry. It is neither public nor under /api/, so anonymous error
    //     reports were 307ing to /login and signed-in ones were being sent to
    //     /en/monitoring, which does not exist. Sentry has not been receiving
    //     client errors from this app at all.
    "/((?!_next/static|_next/image|favicon\\.ico|robots\\.txt|sitemap\\.xml|monitoring|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml)$).*)",
    // Convex Auth proxies signIn/signOut through /api/auth, so it must be matched.
    "/(api|trpc)(.*)",
  ],
};
