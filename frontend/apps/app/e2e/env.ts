/**
 * Where the E2E suite runs. Everything is on this machine, on ports of its own,
 * so a run never touches a dev server, a real deployment or real data:
 *
 *   app      next start on :3100, built into .next-e2e        (e2e/serve.mjs)
 *   preview  the same build on :3101 with PREVIEW_FEATURES=1  (e2e/serve.mjs)
 *   API      the backend on :4100 with the fake LLM           (see playwright.config.ts)
 *   Mailpit  the backend's local mail catcher, for sign-up and reset codes
 *
 * The app is addressed as `localhost`, not 127.0.0.1: Next normalises 127.0.0.1 to
 * localhost in middleware redirects, and cookies are per host name, so a suite on
 * 127.0.0.1 would lose its session on the first redirect.
 */
export const APP_PORT = 3100;
export const APP_URL = `http://localhost:${APP_PORT}`;
export const PREVIEW_PORT = 3101;
export const PREVIEW_URL = `http://localhost:${PREVIEW_PORT}`;
export const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:4100";
export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? "http://127.0.0.1:8025";

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** Refuse anything that is not this machine. Tests must never reach real data. */
export function assertLoopback(name: string, url: string): void {
  const { hostname } = new URL(url);
  if (!LOOPBACK.has(hostname) && !/^127\.\d+\.\d+\.\d+$/.test(hostname)) {
    throw new Error(`${name} must be on this machine (localhost / 127.x), got ${url}. E2E never runs against a remote API.`);
  }
}
