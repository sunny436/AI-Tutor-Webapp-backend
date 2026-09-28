/**
 * Which release this web server runs, for operators.
 *
 * Production runs the checkout /opt/aichat/app with a RELEASE file at its root (written by
 * deploy/server/update.sh on every deploy); the server runs from <checkout>/frontend/apps/app
 * and reads it once, at start: it is the commit this process started from. Outside production
 * (development, tests) the answer is "development".
 *
 * Only reported to local requests: through Cloudflare (which always adds `cf-ray`) the
 * public site never reveals the commit it runs.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

export function parseRelease(text: string | null): string {
  for (const line of text?.split(/\r?\n/) ?? []) {
    if (line.startsWith("commit=")) return line.slice("commit=".length).trim() || "development";
  }
  return "development";
}

function readReleaseFile(dir: string): string | null {
  try {
    return readFileSync(join(dir, "..", "..", "..", "RELEASE"), "utf8");
  } catch {
    return null;
  }
}

let cached: string | undefined;

/** The release of this process (read once: a running process never changes release). */
export function runningRelease(dir: string = process.cwd()): string {
  cached ??= parseRelease(readReleaseFile(dir));
  return cached;
}

/** Requests that came through Cloudflare carry `cf-ray`; only direct local calls see the release. */
export function isLocalRequest(headers: { has(name: string): boolean }): boolean {
  return !headers.has("cf-ray") && !headers.has("cf-connecting-ip");
}

export function healthBody(headers: { has(name: string): boolean }, release: string): Record<string, string> {
  return isLocalRequest(headers) ? { status: "ok", release } : { status: "ok" };
}
