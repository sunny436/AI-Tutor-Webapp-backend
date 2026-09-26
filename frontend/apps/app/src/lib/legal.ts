/**
 * Terms and Privacy Policy links. Shown only once the owner publishes them and sets
 * `NEXT_PUBLIC_TERMS_URL` / `NEXT_PUBLIC_PRIVACY_URL` in web.env (baked in at build time, so a
 * change takes effect with the next deploy). Anything that isn't an http(s) URL counts as unset.
 */

function webUrl(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function legalLinks(): { terms: string | null; privacy: string | null } {
  // Each variable is named in full: Next inlines only literal `process.env.NEXT_PUBLIC_*` reads.
  return {
    terms: webUrl(process.env.NEXT_PUBLIC_TERMS_URL),
    privacy: webUrl(process.env.NEXT_PUBLIC_PRIVACY_URL),
  };
}
