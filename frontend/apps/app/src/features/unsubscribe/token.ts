/**
 * What an unsubscribe link is for, read from its token only to word the page ("Stop daily
 * study reminders?"). The token is `base64url("<user id>:<kind>").<signature>`; only the API
 * can check the signature, and it alone decides what is switched off.
 */
export const EMAIL_KINDS = {
  daily_reminder: "daily study reminders",
  streak_warning: "streak reminders",
  weekly_summary: "weekly summaries",
  security_sign_in: "new sign-in alerts",
} as const;

export type EmailKind = keyof typeof EMAIL_KINDS;

export function isEmailKind(value: unknown): value is EmailKind {
  return typeof value === "string" && Object.hasOwn(EMAIL_KINDS, value);
}

export function kindOfToken(token: string): EmailKind | null {
  const encoded = token.split(".")[0] ?? "";
  if (!/^[A-Za-z0-9_-]+$/.test(encoded)) return null;
  try {
    const padded = encoded.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (encoded.length % 4)) % 4);
    const kind = atob(padded).split(":")[1];
    return isEmailKind(kind) ? kind : null;
  } catch {
    return null;
  }
}
