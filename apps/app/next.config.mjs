import "./src/env.mjs";
import { withSentryConfig } from "@sentry/nextjs";

/**
 * Security headers.
 *
 * Cloudflare can add some of these at the edge, but setting them here means they
 * hold on localhost too, and they survive any change of proxy. HSTS is harmless
 * over plain HTTP — browsers ignore Strict-Transport-Security on non-HTTPS
 * responses — so the same config is correct in dev and in production.
 *
 * CONTENT SECURITY POLICY. Everything this app loads now comes from its own
 * origin: the API is reached through /api/v1 (never from the browser), fonts are
 * self-hosted by next/font, KaTeX's fonts are bundled, and Sentry (when enabled)
 * reports through the same-origin /monitoring tunnel. So connections, images,
 * fonts and objects are locked to 'self'.
 *
 * Scripts and styles still allow 'unsafe-inline': Next 14 writes inline
 * bootstrap scripts without nonces, and KaTeX and Radix use inline styles. The
 * reply renderer never emits raw HTML (see features/markdown), which is the real
 * XSS defence; this policy is the second line — it stops injected content from
 * loading remote scripts or sending data anywhere but here. Dev adds
 * 'unsafe-eval' and ws: for Fast Refresh only.
 */
const isDev = process.env.NODE_ENV !== "production";
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  // Two years, the minimum for preload lists, and applies to subdomains.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  // Stops the browser guessing a response is HTML/JS when it is not.
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Clickjacking: nobody may frame the app (frame-ancestors below says the same).
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  // Do not leak full paths (conversation ids) in the Referer header.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Everything denied. microphone=(self) used to be here and was load-bearing:
  // voice input called getUserMedia({audio:true}), and denying it broke the mic
  // with a permissions error that looked nothing like a header problem. Voice is
  // gone, so the permission goes with it - a page that cannot use a capability
  // should not be asking the browser for it.
  {
    key: "Permissions-Policy",
    value: "microphone=(), camera=(), geolocation=(), interest-cohort=()",
  },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@v1/ui"],
  /**
   * Where the build output goes. `.next` unless told otherwise.
   *
   * The override exists so a build can be VERIFIED without touching the one a
   * running `next start` is serving from. Production here runs from this same
   * working tree, so a plain `next build` rewrites `.next` underneath the live
   * process — which drops chunks for anyone mid-session. Uptime is a hard
   * requirement on this deployment, so:
   *
   *     NEXT_DIST_DIR=.next-verify bun run build
   *
   * proves a change compiles and prerenders without going anywhere near the
   * served output. Unset, behaviour is exactly what it always was.
   */
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Do not advertise the framework version to scanners.
  poweredByHeader: false,
  // The previous app lived under /en, /fr and /es, and the chat at /consult.
  // Temporary redirects, so old bookmarks land somewhere sensible.
  async redirects() {
    return [
      { source: "/:locale(en|fr|es)", destination: "/", permanent: false },
      { source: "/:locale(en|fr|es)/:path*", destination: "/:path*", permanent: false },
      { source: "/consult", destination: "/", permanent: false },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

// ONLY WRAP WHEN THERE IS SOMEWHERE TO SEND ERRORS.
//
// `sentry.client.config.ts` sets `enabled: NODE_ENV === "production"` but takes
// its dsn from NEXT_PUBLIC_SENTRY_DSN, which is EMPTY on the live host. So the
// SDK initialised, reported to nowhere, and still shipped to every browser.
// Measured on /en/login: the Sentry chunk is 95KB gzipped and 316KB to parse,
// out of 302KB gzipped for the whole page — roughly a third of the JavaScript
// on the first screen a user sees, doing nothing at all. On a phone that parse
// cost is the wait people notice after tapping "Get started".
//
// Guarding `enabled` alone would not help: the import is static, so the bundle
// ships either way. The wrapper is what injects it, so the wrapper is what has
// to be conditional.
//
// Set NEXT_PUBLIC_SENTRY_DSN and rebuild to turn it back on. Same options, just
// applied only when they can do something.
const sentryOptions = {
  silent: !process.env.CI,
  telemetry: false,
  widenClientFileUpload: true,
  hideSourceMaps: true,
  disableLogger: true,
  tunnelRoute: "/monitoring",
};

export default process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(nextConfig, sentryOptions)
  : nextConfig;
