import { existsSync } from "node:fs";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

import { SESSION } from "./smoke/support";

/**
 * The production smoke: the live site, as the owner's account, after every deploy.
 *
 *   bun run smoke          (from the repository root; SMOKE_BASE_URL to point elsewhere)
 *
 * Headed in the installed Google Chrome and slowed down, so it can be watched; SMOKE_HEADLESS=1
 * to hide it. One sign-in per run. It writes as little as it can: one question, deleted again
 * (it still counts toward today's learning day, as any question does); the bell's "mark read" and
 * the minute-by-minute activity reports are intercepted; no setting is saved. Dark mode is
 * checked on the page only, never by changing the account's theme. The phones are Playwright's
 * device emulation (WebKit for the iPhone), not real devices.
 */
const headless = process.env.SMOKE_HEADLESS === "1";
// The installed Google Chrome when this machine has one; Playwright's own Chromium otherwise.
const chromeInstalled = [
  join(process.env.LOCALAPPDATA ?? "", "Google", "Chrome", "Application", "chrome.exe"),
  join(process.env.PROGRAMFILES ?? "", "Google", "Chrome", "Application", "chrome.exe"),
  join(process.env["PROGRAMFILES(X86)"] ?? "", "Google", "Chrome", "Application", "chrome.exe"),
  "/opt/google/chrome/chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].some((path) => existsSync(path));
const channel = chromeInstalled ? "chrome" : undefined;

export default defineConfig({
  testDir: "./smoke",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 300_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  outputDir: "./test-results/smoke",
  use: {
    baseURL: process.env.SMOKE_BASE_URL ?? "https://ayur.namahos.com",
    headless,
    launchOptions: { slowMo: headless ? 0 : 150 },
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "sign in", testMatch: /sign-in\.setup\.ts$/, use: { ...devices["Desktop Chrome"], channel }, teardown: "sign out" },
    // Makes its own contexts from the saved session (which may not exist if signing in failed).
    { name: "sign out", testMatch: /sign-out\.teardown\.ts$/, use: { ...devices["Desktop Chrome"], channel } },
    {
      name: "desktop",
      testMatch: /desktop\.smoke\.ts$/,
      dependencies: ["sign in"],
      use: { ...devices["Desktop Chrome"], channel, viewport: { width: 1280, height: 800 }, storageState: SESSION },
    },
    // Independent of "desktop": a failure there must not hide what the phones would show.
    { name: "iphone", testMatch: /phone\.smoke\.ts$/, dependencies: ["sign in"], use: { ...devices["iPhone 14"], storageState: SESSION } },
    { name: "android", testMatch: /phone\.smoke\.ts$/, dependencies: ["sign in"], use: { ...devices["Pixel 7"], channel, storageState: SESSION } },
  ],
});
