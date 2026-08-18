import type { MetadataRoute } from "next";

import { allNotes } from "@/lib/library";
import { siteUrl } from "@/lib/seo";

/**
 * Generated from the notes themselves, so it cannot drift.
 *
 * A hand-maintained sitemap is a list that is wrong the first time somebody adds
 * a note and forgets. Adding `data/knowledge/thyroid.md` should be the only step
 * needed to get `/library/thyroid` crawled, and here it is.
 *
 * Outside `[locale]` for the same reason as `robots.ts`.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();

  return [
    { url: base, changeFrequency: "monthly", priority: 1 },
    { url: `${base}/library`, changeFrequency: "monthly", priority: 0.8 },
    ...allNotes().map((note) => ({
      url: `${base}/library/${note.slug}`,
      changeFrequency: "yearly" as const,
      // Below the index, above nothing. These are the pages meant to rank.
      priority: 0.7,
    })),
  ];
}
