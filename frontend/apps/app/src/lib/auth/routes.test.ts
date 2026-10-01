import { describe, expect, test } from "bun:test";

import { formatPhc, parsePhc } from "./password";
import { AUTH_ROUTES, DISABLED_PATHS, authRoute, withoutTokens } from "./routes";

describe("Better Auth routes this app serves", () => {
  test("exactly the listed method and path reach Better Auth", () => {
    expect(authRoute("POST", "/api/auth/sign-in/email")).toBe("POST /sign-in/email");
    expect(authRoute("get", "/api/auth/get-session")).toBe("GET /get-session");
    expect(authRoute("GET", "/api/auth/callback/google")).toBe("GET /callback/google");
    expect(authRoute("GET", "/api/auth/sign-in/email")).toBeNull(); // wrong method
  });

  test("anything else is refused, however the path is spelled", () => {
    for (const path of [
      "/api/auth/verify-password",
      "/api/auth/sign-up/email",
      "/api/auth/list-sessions",
      "/api/auth/get-access-token",
      "/api/auth/reset-password/some-token",
      "/api/auth//sign-in/email",
      "/api/auth/sign-in//email",
      "/api/auth/sign-in/email/",
      "/api/auth/sign-in%2Femail",
      "/api/auth/Sign-In/Email",
      "/api/auth/../v1/me",
      "/api/authx/sign-in/email",
      "/api/v1/me",
    ]) {
      expect(authRoute("POST", path)).toBeNull();
      expect(authRoute("GET", path)).toBeNull();
    }
  });

  test("nothing disabled inside Better Auth is on the allowlist", () => {
    const allowed = new Set([...AUTH_ROUTES].map((route) => route.split(" ")[1]));
    expect(DISABLED_PATHS.filter((path) => allowed.has(path))).toEqual([]);
  });

  test("no answer carries a session token, at any depth", () => {
    const body = { redirect: false, token: "T1", user: { id: "u" }, session: { id: "s", token: "T2", expiresAt: "x" } };
    expect(withoutTokens(body)).toEqual({ redirect: false, user: { id: "u" }, session: { id: "s", expiresAt: "x" } });
    expect(JSON.stringify(withoutTokens([{ token: "T3" }]))).not.toContain("T3");
    expect(withoutTokens(null)).toBeNull();
  });
});

describe("password hashes (argon2id PHC, as argon2-cffi writes them)", () => {
  // Made by the API's argon2-cffi (t=3, m=64 MiB, p=2); verified under Node in the release checks.
  const FROM_PYTHON = "$argon2id$v=19$m=65536,t=3,p=2$c29tZXNhbHRzb21lc2FsdA$MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI";

  test("a hash the API wrote is read with its own costs, and written back unchanged", () => {
    const phc = parsePhc(FROM_PYTHON);
    expect(phc && [phc.memory, phc.passes, phc.parallelism, phc.salt.length]).toEqual([65536, 3, 2, 16]);
    expect(phc && formatPhc(phc)).toBe(FROM_PYTHON);
  });

  test("anything else is not a hash (never 'verified')", () => {
    for (const value of ["", "!", "$argon2i$v=19$m=65536,t=3,p=2$c2FsdA$aGFzaA", "$argon2id$v=19$m=9999999,t=3,p=2$c29tZXNhbHRzb21lc2FsdA$MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI", "scrypt:abc"]) {
      expect(parsePhc(value)).toBeNull();
    }
  });
});
