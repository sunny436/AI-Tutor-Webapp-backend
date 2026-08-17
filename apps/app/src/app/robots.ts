import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/seo";

/**
 * OUTSIDE `[locale]`, deliberately.
 *
 * `/robots.txt` must be exactly that — not `/en/robots.txt`. The i18n middleware
 * redirects with `urlMappingStrategy: "redirect"`, so anything it matches
 * acquires a locale prefix; a robots file that 307s to a locale-prefixed URL is
 * the same failure mode that once took `/api/` down. The middleware's `matcher`
 * already excludes `robots.txt` and `sitemap.xml` by name for this reason.
 *
 * ⚠ VERIFY AT THE EDGE, NOT JUST LOCALLY. `/robots.txt` on the live host is
 * currently answered by Cloudflare's managed content-signals file, not by this
 * app. If Cloudflare keeps shadowing it, the fix is a zone setting rather than
 * code — but this file has to exist first, or there is nothing to shadow.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          // Signed-in surfaces. Nothing here is useful to a crawler, and several
          // are per-user.
          "/api/",
          "/consult",
          "/files",
          "/jobs",
          "/platform",
          "/settings",
          "/onboarding",
          "/login",
        ],
      },
    ],
    sitemap: `${siteUrl()}/sitemap.xml`,
  };
}
