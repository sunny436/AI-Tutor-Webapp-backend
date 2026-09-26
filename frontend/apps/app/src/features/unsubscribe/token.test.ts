import { describe, expect, test } from "bun:test";

import { kindOfToken } from "./token";

function token(payload: string): string {
  return `${btoa(payload).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "")}.0123456789abcdef0123456789abcdef`;
}

describe("unsubscribe token", () => {
  test("names the kind of email", () => {
    expect(kindOfToken(token("7d9f5f2c-3f7e-4a57-9d0c-3b1f0b6f2a11:daily_reminder"))).toBe("daily_reminder");
    expect(kindOfToken(token("7d9f5f2c-3f7e-4a57-9d0c-3b1f0b6f2a11:security_sign_in"))).toBe("security_sign_in");
  });

  test("anything else names nothing", () => {
    expect(kindOfToken("")).toBeNull();
    expect(kindOfToken("not a token")).toBeNull();
    expect(kindOfToken(token("7d9f5f2c:toString"))).toBeNull();
    expect(kindOfToken(token("7d9f5f2c:__proto__"))).toBeNull();
    expect(kindOfToken("%%%.sig")).toBeNull();
  });
});
