import {
  convexAuthNextjsMiddleware,
  createRouteMatcher,
} from "@convex-dev/auth/nextjs/server";
import { type NextRequest, NextResponse } from "next/server";
import { createI18nMiddleware } from "next-international/middleware";

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
  locales: ["en", "fr", "es"],
  defaultLocale: "en",
  urlMappingStrategy: "redirect",
});

const LOCALES = ["en", "fr", "es"] as const;

/**
 * Everything except these requires a session.
 *
 * The locale-prefixed variants are NOT redundant. `createI18nMiddleware` runs
 * with `urlMappingStrategy: "rewrite"`, so by the time this handler sees the
 * request the path has already become `/en/login` — matching only `/login`
 * classified the login page itself as protected, which redirected it to
 * `/login`, which was rewritten to `/en/login` again: an infinite loop that
 * nested the `redirect` query parameter on every pass until the browser gave up.
 * Nobody could sign in.
 */
const isPublicPage = createRouteMatcher([
  "/login",
  ...LOCALES.map((locale) => `/${locale}/login`),
]);

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
  const isAuthenticated = await convexAuth.isAuthenticated();
  const isPublic = isPublicPage(request);

  if (isPublic && isAuthenticated) {
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
    // Preserve where they were heading so sign-in can return them there, instead
    // of dumping everyone on the dashboard.
    const url = publicUrl(request);
    // Strip the locale the i18n rewrite has already added, so the round trip
    // records "/consult" rather than "/en/consult" — the latter is an internal
    // path that would be rewritten a second time on the way back.
    const bare = request.nextUrl.pathname.replace(/^\/(en|fr|es)(?=\/|$)/, "") || "/";
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
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
    // Convex Auth proxies signIn/signOut through /api/auth, so it must be matched.
    "/(api|trpc)(.*)",
  ],
};
