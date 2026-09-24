/**
 * The session cookie. The backend issues an opaque session token; the browser
 * holds it only in this httpOnly cookie, and only the BFF reads it.
 *
 * NAME: `__Host-aichat_session` on HTTPS. The `__Host-` prefix makes the browser
 * refuse the cookie unless it is Secure, host-only (no Domain) and Path=/ — so a
 * sibling subdomain in the same zone (this zone is shared with other sites) cannot
 * plant or overwrite it. Plain-HTTP local development cannot use the prefix, so it
 * falls back to `aichat_session`.
 */

export const SECURE_COOKIE = "__Host-aichat_session";
export const PLAIN_COOKIE = "aichat_session";

/** Read the session token from a `Cookie` header (either name). */
export function readSessionToken(cookieHeader: string | null | undefined, https: boolean): string | null {
  if (!cookieHeader) return null;
  const values = new Map<string, string>();
  for (const part of cookieHeader.split(";")) {
    const index = part.indexOf("=");
    if (index === -1) continue;
    const name = part.slice(0, index).trim();
    const value = part.slice(index + 1).trim();
    if (name && !values.has(name)) values.set(name, value);
  }
  // On HTTPS only the prefixed cookie is trusted: the plain one could have been
  // set by anything that can write cookies for this host.
  const raw = https ? values.get(SECURE_COOKIE) : (values.get(PLAIN_COOKIE) ?? values.get(SECURE_COOKIE));
  if (!raw) return null;
  try {
    const token = decodeURIComponent(raw);
    return token || null;
  } catch {
    return null;
  }
}

/** `Set-Cookie` value that stores the session until `expiresAt`. */
export function sessionCookie(token: string, expiresAt: string, https: boolean, now = Date.now()): string {
  const expires = Date.parse(expiresAt);
  const maxAge = Number.isFinite(expires) ? Math.max(0, Math.floor((expires - now) / 1000)) : 0;
  const name = https ? SECURE_COOKIE : PLAIN_COOKIE;
  return `${name}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${
    https ? "; Secure" : ""
  }`;
}

/** `Set-Cookie` values that delete the session cookie. */
export function clearedSessionCookies(https: boolean): string[] {
  const cleared = [`${PLAIN_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${https ? "; Secure" : ""}`];
  // A `__Host-` cookie can only be touched over HTTPS; the browser ignores the attempt otherwise.
  if (https) cleared.push(`${SECURE_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Secure`);
  return cleared;
}

/** Cheap presence check for middleware, which only gates pages. */
export function hasSessionCookie(cookieHeader: string | null | undefined): boolean {
  if (!cookieHeader) return false;
  return new RegExp(`(?:^|;\\s*)(?:${SECURE_COOKIE}|${PLAIN_COOKIE})=[^;]+`).test(cookieHeader);
}
