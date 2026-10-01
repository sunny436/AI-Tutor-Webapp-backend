import { describe, expect, test } from "bun:test";
import { serializeSignedCookie } from "better-call";

import { SECURE_COOKIE } from "./cookies";
import { handleSessionExpired } from "./expired";

const API = "http://127.0.0.1:4000";
const SECRET = "a-test-secret-that-is-long-enough-for-better-auth";
const SIGNED = (await serializeSignedCookie(SECURE_COOKIE, "tok12345678901234567", SECRET)).split(";")[0] as string;

function request(path: string, cookie: string | null = SIGNED): Request {
  const headers = new Headers({ host: "chat.example.com", "x-forwarded-proto": "https" });
  if (cookie) headers.set("cookie", cookie);
  return new Request(`http://localhost:3000${path}`, { headers });
}

const api = (status: number) =>
  (async () =>
    new Response(status === 200 ? JSON.stringify({ id: "u" }) : "{}", { status })) as unknown as typeof fetch;

describe("/api/session/expired", () => {
  test("a session the API rejects is cleared and sent to sign in, keeping a safe destination", async () => {
    const response = await handleSessionExpired(request("/api/session/expired?redirect=/settings"), {
      apiBaseUrl: API,
      cookieSecret: SECRET,
      fetchImpl: api(401),
    });
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("https://chat.example.com/login?reason=expired&redirect=%2Fsettings");
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  test("a hostile link cannot sign a valid session out", async () => {
    const response = await handleSessionExpired(request("/api/session/expired"), {
      apiBaseUrl: API,
      cookieSecret: SECRET,
      fetchImpl: api(200),
    });
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("location")).toBe("https://chat.example.com/");
  });

  test("an outage does not sign anyone out", async () => {
    const response = await handleSessionExpired(request("/api/session/expired"), {
      apiBaseUrl: API,
      cookieSecret: SECRET,
      fetchImpl: api(503),
    });
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  test("an unsafe redirect is dropped", async () => {
    const response = await handleSessionExpired(request("/api/session/expired?redirect=//evil.com", null), {
      apiBaseUrl: API,
      cookieSecret: SECRET,
      fetchImpl: api(401),
    });
    expect(response.headers.get("location")).toBe("https://chat.example.com/login?reason=expired");
  });
});
