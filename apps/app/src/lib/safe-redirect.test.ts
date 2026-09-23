import { describe, expect, test } from "bun:test";
import { safeRedirect } from "./safe-redirect";

describe("safeRedirect", () => {
  test("keeps in-app paths with their query and hash", () => {
    expect(safeRedirect("/")).toBe("/");
    expect(safeRedirect("/settings")).toBe("/settings");
    expect(safeRedirect("/c/11111111-1111-4111-8111-111111111111?x=1#m")).toBe(
      "/c/11111111-1111-4111-8111-111111111111?x=1#m",
    );
  });

  test("rejects other origins and protocol tricks", () => {
    for (const target of [
      "https://evil.com",
      "//evil.com",
      "/\\evil.com",
      "\\\\evil.com",
      "/%5Cevil.com",
      "/%5C%5Cevil.com",
      "/%2F%2Fevil.com",
      "javascript:alert(1)",
      "evil.com",
      "/\tevil",
      "/\nhttps://evil.com",
      "",
      null,
      undefined,
    ]) {
      expect(safeRedirect(target as string)).toBe("/");
    }
  });

  test("does not send people to the API or back to the auth pages", () => {
    expect(safeRedirect("/api/v1/me")).toBe("/");
    expect(safeRedirect("/login")).toBe("/");
    expect(safeRedirect("/signup?x=1")).toBe("/");
  });

  test("uses the fallback given", () => {
    expect(safeRedirect("//evil.com", "/settings")).toBe("/settings");
  });

  test("refuses malformed percent-encoding and absurd lengths", () => {
    expect(safeRedirect("/%E0%A4%A")).toBe("/");
    expect(safeRedirect(`/${"a".repeat(3000)}`)).toBe("/");
  });
});
