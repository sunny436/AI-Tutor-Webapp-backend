/**
 * What the auth pages may offer, read on the server per request. Kept apart from config.ts so a
 * page asking "is Google on?" never loads Better Auth or the database driver.
 */
export function googleEnabled(env: Record<string, string | undefined> = process.env): boolean {
  return Boolean(env.GOOGLE_CLIENT_ID?.trim() && env.GOOGLE_CLIENT_SECRET?.trim());
}
