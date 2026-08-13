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
 * No Content-Security-Policy yet: this app loads Convex, Google sign-in and
 * Sentry, and a CSP written blind would break one of them silently. That needs
 * measuring real traffic first, so it is deliberately left out rather than
 * guessed at.
 */
const securityHeaders = [
  // Two years, the minimum for preload lists, and applies to subdomains.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  // Stops the browser guessing a response is HTML/JS when it is not — the trick
  // behind most "upload a file, get XSS" bugs. Report uploads make this relevant.
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Clickjacking: nobody may frame the dashboard.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
  // Do not leak the full path of a health page in the Referer header.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // microphone=(self) is REQUIRED, not an oversight: use-voice.ts calls
  // getUserMedia({audio:true}) for voice input. Denying it here breaks the mic
  // button with a permissions error that looks nothing like a header problem.
  // Camera and geolocation are genuinely unused, so they stay denied.
  {
    key: "Permissions-Policy",
    value: "microphone=(self), camera=(), geolocation=(), interest-cohort=()",
  },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@v1/ui", "@v1/backend"],
  // Do not advertise the framework version to scanners.
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default withSentryConfig(nextConfig, {
  silent: !process.env.CI,
  telemetry: false,
  widenClientFileUpload: true,
  hideSourceMaps: true,
  disableLogger: true,
  tunnelRoute: "/monitoring",
});
