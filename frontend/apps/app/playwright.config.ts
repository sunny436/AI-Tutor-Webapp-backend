import { existsSync } from "node:fs";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

import { API_URL, APP_PORT, APP_URL, PREVIEW_PORT, PREVIEW_URL, assertLoopback } from "./e2e/env";

/**
 * End-to-end tests: a production build of this app against a LOCAL backend with
 * the fake LLM (it echoes "You said: …" word by word). Never a real deployment.
 *
 *   bun run test:e2e
 *
 * The backend on :4100 is reused if it is already running (the global setup checks
 * it); otherwise it is started from this repository's `backend/` (or from
 * E2E_BACKEND_DIR, if set), using that directory's local .env (database, Mailpit)
 * with the overrides below on top. E2E_BACKEND_DIR=none never starts it.
 */
assertLoopback("E2E_API_URL", API_URL);

const python = process.platform === "win32" ? join(".venv", "Scripts", "python.exe") : join(".venv", "bin", "python");
const repoBackend = join(__dirname, "..", "..", "..", "backend");
const requested = process.env.E2E_BACKEND_DIR;
const backendDir =
  requested === "none" ? undefined : requested || (existsSync(join(repoBackend, python)) ? repoBackend : undefined);

/** Shared by the e2e API and web servers (never a real token). */
const E2E_INTERNAL_TOKEN = "e2e-only-internal-token-0123456789abcdef";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  // One account per test, one server: run in order, so a slow machine does not
  // turn timing-sensitive checks (streaming, scrolling) into flakes.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: "./test-results",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: APP_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /(mobile|preview)\.e2e\.ts$/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.e2e\.ts$/ },
    // The same build with PREVIEW_FEATURES=1 (e2e/serve.mjs).
    { name: "preview", use: { ...devices["Desktop Chrome"], baseURL: PREVIEW_URL }, testMatch: /preview\.e2e\.ts$/ },
    // Safari-class engines for the Settings workspace (navigation, focus, history, the phone list).
    { name: "webkit", use: { ...devices["Desktop Safari"] }, testMatch: /settings-workspace\.e2e\.ts$/ },
    { name: "webkit-mobile", use: { ...devices["iPhone 14"] }, testMatch: /settings-mobile\.e2e\.ts$/ },
  ],
  webServer: [
    ...(backendDir
      ? [
          {
            command: `${python} -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port ${new URL(API_URL).port}`,
            cwd: backendDir,
            url: `${API_URL}/ready`,
            reuseExistingServer: true,
            timeout: 60_000,
            env: {
              LLM_PROVIDER: "fake",
              // Slow enough to press Stop and switch chats mid-reply.
              LLM_FAKE_TOKEN_DELAY_S: "0.05",
              // Every test signs up and chats; the production limits would trip.
              CODE_REQUESTS_PER_EMAIL: "1000",
              CHAT_GENERATIONS_PER_MINUTE: "1000",
              CHAT_GENERATIONS_PER_DAY: "100000",
              // Shared with the web app's Better Auth (below): it asks the API to email codes.
              AUTH_INTERNAL_TOKEN: E2E_INTERNAL_TOKEN,
              // Voice mode with the API's fake speech (app/voice/provider.py FakeVoice): e2e/voice*.e2e.ts.
              VOICE_MODE: "on",
              VOICE_PROVIDER: "fake",
            },
          },
        ]
      : []),
    {
      // Node, the pinned runtime of production (.node-version); serve.mjs runs next with it.
      command: "node e2e/serve.mjs",
      url: `http://127.0.0.1:${APP_PORT}/login`,
      // A server already on :3100 is not ours to trust (wrong build, wrong API).
      // E2E_REUSE_APP=1 opts in, e.g. with E2E_SKIP_BUILD while iterating on tests.
      reuseExistingServer: process.env.E2E_REUSE_APP === "1",
      timeout: 300_000,
      stdout: "pipe",
      env: {
        PORT: String(APP_PORT),
        PREVIEW_PORT: String(PREVIEW_PORT),
        NEXT_DIST_DIR: ".next-e2e",
        API_BASE_URL: API_URL,
        NEXT_PUBLIC_SITE_URL: APP_URL,
        // Better Auth (lib/auth): the API's own test database (the API's default DATABASE_URL, as CI
        // runs it), a throwaway secret, and no per-IP limit (every test comes from one address;
        // the per-account limits stay on).
        AUTH_DATABASE_URL: process.env.E2E_AUTH_DATABASE_URL ?? "postgresql://aichat:aichat@127.0.0.1:5432/aichat",
        BETTER_AUTH_SECRET: "e2e-only-better-auth-secret-0123456789abcdef",
        AUTH_INTERNAL_TOKEN: E2E_INTERNAL_TOKEN,
        AUTH_RATE_LIMIT: "off",
        ...(process.env.E2E_GOOGLE ? { GOOGLE_CLIENT_ID: "e2e-client-id", GOOGLE_CLIENT_SECRET: "e2e-client-secret" } : {}),
        // Whatever a local .env.local says: no error reporting from test runs.
        NEXT_PUBLIC_SENTRY_DSN: "",
      },
    },
  ],
});
