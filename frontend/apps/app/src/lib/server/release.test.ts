import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { healthBody, isLocalRequest, parseRelease, runningRelease } from "./release";

const SHA = "0123456789abcdef0123456789abcdef01234567";

describe("release", () => {
  test("parses the commit from the release file", () => {
    expect(parseRelease(`commit=${SHA}\nprepared=2026-09-24T00:00:00Z\n`)).toBe(SHA);
    expect(parseRelease(`prepared=x\r\ncommit=${SHA}\r\n`)).toBe(SHA);
    expect(parseRelease("prepared=x\n")).toBe("development");
    expect(parseRelease(null)).toBe("development");
  });

  test("reads RELEASE at the release root, three levels above frontend/apps/app", () => {
    const root = mkdtempSync(join(tmpdir(), "release-"));
    const app = join(root, "frontend", "apps", "app");
    mkdirSync(app, { recursive: true });
    writeFileSync(join(root, "RELEASE"), `commit=${SHA}\n`);
    expect(runningRelease(app)).toBe(SHA);
  });

  test("only local requests see the release; Cloudflare traffic does not", () => {
    const local = new Headers();
    const viaCloudflare = new Headers({ "cf-ray": "8a1b2c3d4e5f-AMS", "cf-connecting-ip": "203.0.113.9" });
    expect(isLocalRequest(local)).toBe(true);
    expect(isLocalRequest(viaCloudflare)).toBe(false);
    expect(healthBody(local, SHA)).toEqual({ status: "ok", release: SHA });
    expect(healthBody(viaCloudflare, SHA)).toEqual({ status: "ok" });
  });
});
