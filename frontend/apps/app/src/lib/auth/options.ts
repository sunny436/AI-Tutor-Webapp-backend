/**
 * What the auth pages may offer, read on the server per request. Kept apart from config.ts so a
 * page asking "is Google on?" never loads Better Auth or the database driver.
 */
export function googleEnabled(env: Record<string, string | undefined> = process.env): boolean {
  return Boolean(env.GOOGLE_CLIENT_ID?.trim() && env.GOOGLE_CLIENT_SECRET?.trim());
}

/** Turnstile's public site key when the CAPTCHA is configured (both keys), else null. */
export function turnstileSiteKey(env: Record<string, string | undefined> = process.env): string | null {
  const siteKey = env.TURNSTILE_SITE_KEY?.trim();
  return siteKey && env.TURNSTILE_SECRET_KEY?.trim() ? siteKey : null;
}
