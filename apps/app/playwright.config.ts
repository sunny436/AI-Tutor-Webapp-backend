import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

import { API_URL, APP_PORT, APP_URL, assertLoopback } from "./e2e/env";

/**
 * End-to-end tests: a production build of this app against a LOCAL backend with
 * the fake LLM (it echoes "You said: …" word by word). Never a real deployment.
 *
 *   bun run test:e2e
 *
 * The backend on :4100 is either already running (the global setup checks it) or
 * started here when E2E_BACKEND_DIR points at the backend's `backend-python`
 * directory. Either way it uses that checkout's own local .env (database, Mailpit),
 * with the overrides below on top.
 */
assertLoopback("E2E_API_URL", API_URL);

const backendDir = process.env.E2E_BACKEND_DIR;
const python = process.platform === "win32" ? join(".venv", "Scripts", "python.exe") : join(".venv", "bin", "python");

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
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.e2e\.ts$/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.e2e\.ts$/ },
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
      command: "node e2e/serve.mjs",
      url: `http://127.0.0.1:${APP_PORT}/login`,
      // A server already on :3100 is not ours to trust (wrong build, wrong API).
      // E2E_REUSE_APP=1 opts in, e.g. with E2E_SKIP_BUILD while iterating on tests.
      reuseExistingServer: process.env.E2E_REUSE_APP === "1",
      timeout: 300_000,
      stdout: "pipe",
      env: {
        PORT: String(APP_PORT),
        NEXT_DIST_DIR: ".next-e2e",
        API_BASE_URL: API_URL,
        NEXT_PUBLIC_SITE_URL: APP_URL,
        // Whatever a local .env.local says: no error reporting from test runs.
        NEXT_PUBLIC_SENTRY_DSN: "",
      },
    },
  ],
});
