/**
 * One place that knows the site's public address.
 *
 * Every canonical URL, sitemap entry and JSON-LD `url` has to agree, and they
 * have to be ABSOLUTE. A relative canonical is ignored; a canonical pointing at
 * localhost is worse than none at all, because it tells a crawler the real page
 * is somewhere it cannot reach.
 *
 * `NEXT_PUBLIC_SITE_URL` is the deployed origin. The localhost fallback exists so
 * `next dev` works, and is never what production should be using — if these URLs
 * come out as localhost in a built page, that env var is missing.
 */

const FALLBACK = "http://localhost:3000";

export function siteUrl(): string {
  return (process.env.NEXT_PUBLIC_SITE_URL || FALLBACK).replace(/\/+$/, "");
}

/** An absolute canonical URL for a path like `/library/acidity`. */
export function canonical(pathname: string): string {
  return `${siteUrl()}${pathname.startsWith("/") ? pathname : `/${pathname}`}`;
}

/**
 * The organisation behind the content.
 *
 * DELIBERATELY MINIMAL. Everything here is verifiable from the product itself.
 * No founder name, no address, no credentials, no review board — health content
 * is held to an experience/expertise bar that is met by a real, named,
 * credentialed reviewer, and inventing one to satisfy a schema validator would be
 * a fabricated claim about medical oversight. The slots exist in the page
 * templates; they stay empty until a real person fills them.
 */
export function organizationJsonLd() {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "Ayurveda by Ollasoftware",
    url: siteUrl(),
  };
}
