/**
 * The session cookie. Better Auth (lib/auth) issues it; the BFF and server components only read
 * it, and the browser never sees the token (the cookie is httpOnly, and the token is stripped
 * from every /api/auth answer).
 *
 * NAME: `__Host-padhai_session` on HTTPS. The `__Host-` prefix makes the browser refuse the
 * cookie unless it is Secure, host-only (no Domain) and Path=/ — so a sibling subdomain in the
 * same zone (this zone is shared with other sites) cannot plant or overwrite it. Plain-HTTP local
 * development cannot use the prefix, so it falls back to `padhai_session`.
 *
 * VALUE: Better Auth signs it: encodeURIComponent(token + "." + base64(HMAC-SHA256(secret, token)))
 * (better-call's signCookieValue). The signature is verified here with BETTER_AUTH_SECRET before
 * the token goes anywhere, so a token alone (leaked, or guessed at) never makes a cookie that
 * works. The API then checks the token itself against auth_sessions.
 *
 * The cookie of the release before Better Auth (`__Host-aichat_session`) is no longer read, only
 * cleared on sign-out.
 */

export const SECURE_COOKIE = "__Host-padhai_session";
export const PLAIN_COOKIE = "padhai_session";
const LEGACY_SECURE_COOKIE = "__Host-aichat_session";
const LEGACY_PLAIN_COOKIE = "aichat_session";

/** The raw (still signed) value of the session cookie in a `Cookie` header. */
export function sessionCookieValue(cookieHeader: string | null | undefined, https: boolean): string | null {
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
  return raw || null;
}

const encoder = new TextEncoder();
const keys = new Map<string, Promise<CryptoKey>>();

function hmacKey(secret: string): Promise<CryptoKey> {
  let key = keys.get(secret);
  if (!key) {
    key = crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
    keys.set(secret, key);
  }
  return key;
}

/** The token inside a signed cookie value, or null when the signature does not hold. */
export async function verifySignedToken(value: string, secret: string): Promise<string | null> {
  if (!secret) return null;
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return null;
  }
  const dot = decoded.lastIndexOf(".");
  if (dot < 1) return null;
  const token = decoded.slice(0, dot);
  const signature = decoded.slice(dot + 1);
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(token) || !/^[A-Za-z0-9+/]{43}=$/.test(signature)) return null;
  let bytes: Uint8Array;
  try {
    bytes = Uint8Array.from(atob(signature), (char) => char.charCodeAt(0));
  } catch {
    return null;
  }
  const valid = await crypto.subtle.verify("HMAC", await hmacKey(secret), bytes, encoder.encode(token));
  return valid ? token : null;
}

/** The session token from a `Cookie` header, once its signature is verified. */
export async function readSessionToken(
  cookieHeader: string | null | undefined,
  https: boolean,
  secret: string,
): Promise<string | null> {
  const value = sessionCookieValue(cookieHeader, https);
  return value ? verifySignedToken(value, secret) : null;
}

/** `Set-Cookie` values that delete the session cookie (and the one before Better Auth). */
export function clearedSessionCookies(https: boolean): string[] {
  const cleared = [PLAIN_COOKIE, LEGACY_PLAIN_COOKIE].map(
    (name) => `${name}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${https ? "; Secure" : ""}`,
  );
  // A `__Host-` cookie can only be touched over HTTPS; the browser ignores the attempt otherwise.
  if (https) {
    for (const name of [SECURE_COOKIE, LEGACY_SECURE_COOKIE]) {
      cleared.push(`${name}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Secure`);
    }
  }
  return cleared;
}

/** Cheap presence check for middleware, which only gates pages. */
export function hasSessionCookie(cookieHeader: string | null | undefined): boolean {
  if (!cookieHeader) return false;
  return new RegExp(`(?:^|;\\s*)(?:${SECURE_COOKIE}|${PLAIN_COOKIE})=[^;]+`).test(cookieHeader);
}
