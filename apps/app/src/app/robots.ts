import type { MetadataRoute } from "next";

/**
 * A private chat app has nothing to index. Outside every route group so it is
 * served at exactly `/robots.txt` (the middleware matcher skips it too).
 */
export default function robots(): MetadataRoute.Robots {
  return { rules: [{ userAgent: "*", disallow: "/" }] };
}
