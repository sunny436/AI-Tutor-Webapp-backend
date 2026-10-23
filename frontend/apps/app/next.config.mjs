import { createRequire } from "node:module";

import "./src/env.mjs";
import { withSentryConfig } from "@sentry/nextjs";

/**
 * ONE KaTeX for the whole app. rehype-katex and mermaid import "katex" too, and a copy nested
 * under one of them (an older install leaves it behind; bun does not remove it) would be a second
 * KaTeX without the mhchem chemistry macros the reply renderer registers (features/markdown).
 */
const KATEX = createRequire(import.meta.url).resolve("katex").replace(/katex\.js$/, "katex.mjs");

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
 *
 * Outside origins: Cloudflare Turnstile (challenges.cloudflare.com), the CAPTCHA the sign-in
 * form shows only when an address is being hammered (lib/auth/config.ts): its script, and the
 * iframe it draws the check in. And Cloudflare Web Analytics, which the site's Cloudflare zone adds
 * to every page it serves (cookieless page timings; Cloudflare already carries every request):
 * its script and where it reports. Blocked, it was a console error on every page (2026-10-23).
 */
const isDev = process.env.NODE_ENV !== "production";
const TURNSTILE = "https://challenges.cloudflare.com";
const CF_INSIGHTS = { script: "https://static.cloudflareinsights.com", report: "https://cloudflareinsights.com" };
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' ${TURNSTILE} ${CF_INSIGHTS.script}${isDev ? " 'unsafe-eval'" : ""}`,
  `frame-src ${TURNSTILE}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${CF_INSIGHTS.report}${isDev ? " ws: wss:" : ""}`,
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
  // The microphone for this site only (dictation: the browser's own speech recognition,
  // features/chat/use-dictation.ts); denying it makes recognition fail with "not-allowed",
  // an error that looks nothing like a header problem. Everything else stays denied.
  {
    key: "Permissions-Policy",
    value: "microphone=(self), camera=(), geolocation=(), interest-cohort=()",
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
  // The host builds under a 2 GB memory cap (deploy/server/lib.sh). Compile in a worker that exits
  // after each compiler (a custom webpack config would otherwise turn it off) and prerender on
  // one CPU, so mermaid, pdf.js and the other reply libraries do not push the build over it.
  // `pg` (Better Auth's database, lib/auth) stays a plain Node require: bundling it pulls in its
  // optional native driver.
  experimental: { webpackBuildWorker: true, cpus: 1 },
  serverExternalPackages: ["pg"],
  // Do not advertise the framework version to scanners.
  poweredByHeader: false,
  // No next/image here, so no image optimizer: /_next/image answers 404 (Next 14 has open
  // advisories in it, e.g. GHSA-2xp9-vwfh-vxw4). Middleware can't block it: Next serves that
  // route before middleware runs.
  images: { unoptimized: true },
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
  webpack(config) {
    config.resolve.alias = { ...config.resolve.alias, katex$: KATEX };
    return config;
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
