import { describe, expect, test } from "bun:test";
// The function Better Auth sets its session cookie with: what the BFF reads must be exactly that.
import { serializeSignedCookie } from "better-call";

import {
  PLAIN_COOKIE,
  SECURE_COOKIE,
  clearedSessionCookies,
  hasSessionCookie,
  readSessionToken,
  verifySignedToken,
} from "./cookies";

const SECRET = "a-test-secret-that-is-long-enough-for-better-auth";
const TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz012345";

/** `name=value` as Better Auth writes it, value signed with `secret`. */
async function betterAuthCookie(name: string, token: string, secret = SECRET): Promise<string> {
  return (await serializeSignedCookie(name, token, secret)).split(";")[0] as string;
}

describe("session cookie", () => {
  test("a cookie Better Auth signed gives its token back", async () => {
    const cookie = await betterAuthCookie(SECURE_COOKIE, TOKEN);
    expect(await readSessionToken(`theme=dark; ${cookie}`, true, SECRET)).toBe(TOKEN);
  });

  test("a token alone, a tampered or foreign signature, or no secret never yields a session", async () => {
    const cookie = await betterAuthCookie(SECURE_COOKIE, TOKEN);
    const value = cookie.slice(cookie.indexOf("=") + 1);
    expect(await readSessionToken(`${SECURE_COOKIE}=${TOKEN}`, true, SECRET)).toBeNull(); // raw token
    expect(await verifySignedToken(value.replace(TOKEN, `${TOKEN.slice(0, -1)}X`), SECRET)).toBeNull(); // other token
    expect(await verifySignedToken(`${TOKEN}.${"A".repeat(43)}=`, SECRET)).toBeNull(); // made-up signature
    expect(await verifySignedToken(value, "another-secret-another-secret-another")).toBeNull();
    expect(await verifySignedToken(value, "")).toBeNull();
  });

  test("on HTTPS only the __Host- cookie is trusted", async () => {
    const planted = await betterAuthCookie(PLAIN_COOKIE, TOKEN);
    expect(await readSessionToken(planted, true, SECRET)).toBeNull();
    expect(await readSessionToken(planted, false, SECRET)).toBe(TOKEN); // local dev over HTTP
  });

  test("clearing deletes the new and the old names over HTTPS, only the plain ones over HTTP", () => {
    const https = clearedSessionCookies(true).map((cookie) => cookie.split("=")[0]);
    expect(https.sort()).toEqual(["__Host-aichat_session", SECURE_COOKIE, "aichat_session", PLAIN_COOKIE].sort());
    expect(clearedSessionCookies(false).every((cookie) => !cookie.includes("Secure"))).toBe(true);
  });

  test("presence check for middleware", () => {
    expect(hasSessionCookie(`theme=dark; ${SECURE_COOKIE}=x`)).toBe(true);
    expect(hasSessionCookie(`${PLAIN_COOKIE}=`)).toBe(false);
    expect(hasSessionCookie("__Host-aichat_session=old")).toBe(false); // the cookie before Better Auth
    expect(hasSessionCookie(null)).toBe(false);
  });
});
