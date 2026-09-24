/**
 * The public address of the app, for absolute metadata URLs. Set
 * `NEXT_PUBLIC_SITE_URL` in production; the fallback exists for local runs.
 */
export function siteUrl(): string {
  return (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/+$/, "");
}
