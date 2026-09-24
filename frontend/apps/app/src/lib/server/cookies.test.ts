import { describe, expect, test } from "bun:test";
import {
  PLAIN_COOKIE,
  SECURE_COOKIE,
  clearedSessionCookies,
  hasSessionCookie,
  readSessionToken,
  sessionCookie,
} from "./cookies";

describe("session cookie", () => {
  test("HTTPS uses the __Host- prefix, Secure, HttpOnly, SameSite=Lax, Path=/", () => {
    const cookie = sessionCookie("tok", "2030-01-01T00:00:10Z", true, Date.parse("2030-01-01T00:00:00Z"));
    expect(cookie).toBe(`${SECURE_COOKIE}=tok; Path=/; HttpOnly; SameSite=Lax; Max-Age=10; Secure`);
  });

  test("plain HTTP (local dev) cannot use the prefix", () => {
    const cookie = sessionCookie("tok", "2030-01-01T00:00:10Z", false, Date.parse("2030-01-01T00:00:00Z"));
    expect(cookie.startsWith(`${PLAIN_COOKIE}=tok;`)).toBe(true);
    expect(cookie).not.toContain("Secure");
    expect(cookie).toContain("HttpOnly");
  });

  test("an unparseable expiry never produces a long-lived cookie", () => {
    expect(sessionCookie("tok", "garbage", true)).toContain("Max-Age=0");
  });

  test("on HTTPS only the __Host- cookie is trusted", () => {
    expect(readSessionToken(`${PLAIN_COOKIE}=planted`, true)).toBeNull();
    expect(readSessionToken(`${PLAIN_COOKIE}=planted; ${SECURE_COOKIE}=real`, true)).toBe("real");
    expect(readSessionToken(`${PLAIN_COOKIE}=dev`, false)).toBe("dev");
  });

  test("clearing deletes both names over HTTPS, only the plain one over HTTP", () => {
    expect(clearedSessionCookies(true).length).toBe(2);
    expect(clearedSessionCookies(false)).toEqual([`${PLAIN_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`]);
  });

  test("presence check for middleware", () => {
    expect(hasSessionCookie(`theme=dark; ${SECURE_COOKIE}=x`)).toBe(true);
    expect(hasSessionCookie(`${PLAIN_COOKIE}=`)).toBe(false);
    expect(hasSessionCookie("other=1")).toBe(false);
    expect(hasSessionCookie(null)).toBe(false);
  });
});
