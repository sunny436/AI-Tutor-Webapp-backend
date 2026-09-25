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
              SIGNUP_ATTEMPTS_PER_IP: "1000",
              LOGIN_ATTEMPTS_PER_IP: "1000",
              LOGIN_FAILURES_PER_EMAIL: "1000",
              CODE_REQUESTS_PER_EMAIL: "1000",
              CHAT_GENERATIONS_PER_MINUTE: "1000",
              CHAT_GENERATIONS_PER_DAY: "100000",
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
        // Whatever a local .env.local says: no error reporting from test runs.
        NEXT_PUBLIC_SENTRY_DSN: "",
      },
    },
  ],
});
