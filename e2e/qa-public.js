/**
 * The signed-OUT surface of the live site, driven in a real browser.
 *
 *   node qa-public.js                      (defaults to the public site)
 *   E2E_BASE_URL=http://localhost:3000 node qa-public.js
 *
 * Everything here runs without credentials, which is the point: it is the half
 * of the QA sweep that does not need a mailbox to read verification codes from.
 *
 * What it proves:
 *   - the login page renders and its form validates
 *   - a signed-out visitor cannot reach any dashboard route
 *   - the app survives nonsense URLs, locale prefixes and back/forward
 *   - no console errors and no failed requests on any public page
 *   - the layout does not overflow horizontally at nine viewport sizes
 *
 * Console errors and failed responses are collected per page rather than
 * globally, so a failure names the page that produced it.
 */
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL || "https://ayur.namahos.com";

const results = [];
const record = (name, status, detail = "") => {
  results.push({ name, status, detail });
  console.log(`${status}  ${name}${detail ? ` - ${detail}` : ""}`);
};

// Noise that is not the application's fault and would only train us to ignore
// real failures: extension traffic, analytics that are intentionally unset, and
// the favicon a dev server does not serve.
const IGNORE = /favicon|openpanel|sentry|_vercel|chrome-extension|analytics/i;

/** Attach collectors and return a drain function. */
function watch(page) {
  const errors = [];
  const failed = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !IGNORE.test(m.text())) errors.push(m.text().slice(0, 160));
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${String(e).slice(0, 160)}`));
  page.on("response", (r) => {
    if (r.status() >= 400 && !IGNORE.test(r.url())) failed.push(`${r.status()} ${r.url().slice(0, 110)}`);
  });
  return () => ({ errors: errors.splice(0), failed: failed.splice(0) });
}

const VIEWPORTS = [
  { w: 1920, h: 1080, name: "1920x1080 desktop" },
  { w: 1440, h: 900, name: "1440x900 laptop" },
  { w: 1366, h: 768, name: "1366x768 laptop" },
  { w: 1280, h: 800, name: "1280x800 laptop" },
  { w: 1024, h: 768, name: "1024x768 tablet-ls" },
  { w: 768, h: 1024, name: "768x1024 tablet-pt" },
  { w: 390, h: 844, name: "390x844 mobile" },
  { w: 375, h: 667, name: "375x667 mobile-sm" },
  { w: 360, h: 800, name: "360x800 mobile-sm" },
];

(async () => {
  const browser = await chromium.launch({ headless: process.env.E2E_HEADED !== "1" });
  const context = await browser.newContext();
  const page = await context.newPage();
  const drain = watch(page);

  try {
    // ---- 1. the login page renders ----------------------------------------
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('form.w-72 input[type="email"]', { timeout: 40000 });
    let seen = drain();
    record("login page renders its form", "PASS", page.url());
    record(
      "login page is free of console errors",
      seen.errors.length ? "FAIL" : "PASS",
      seen.errors[0] || "clean",
    );
    record(
      "login page has no failed requests",
      seen.failed.length ? "FAIL" : "PASS",
      seen.failed[0] || "clean",
    );

    // ---- 2. form validation ------------------------------------------------
    const form = page.locator("form.w-72");

    // Empty submit must not navigate away or throw.
    await form.locator('button[type="submit"]').click().catch(() => {});
    await page.waitForTimeout(1200);
    record(
      "empty submit stays on the login page",
      page.url().includes("/login") ? "PASS" : "FAIL",
      page.url(),
    );

    // An address the browser itself rejects must not reach the server.
    await form.locator('input[type="email"]').fill("not-an-email");
    await form.locator('input[type="password"]').fill("x");
    await form.locator('button[type="submit"]').click().catch(() => {});
    await page.waitForTimeout(1500);
    record(
      "invalid email is rejected client-side",
      page.url().includes("/login") ? "PASS" : "FAIL",
      page.url(),
    );

    // A well-formed address that does not exist, with a wrong password.
    drain();
    await form.locator('input[type="email"]').fill("definitely-not-a-user@example.com");
    await form.locator('input[type="password"]').fill("WrongPassword#123");
    await form.locator('button[type="submit"]').click().catch(() => {});
    await page.waitForTimeout(6000);
    const bodyText = (await page.locator("body").innerText().catch(() => "")) || "";
    const stillOnLogin = page.url().includes("/login");
    record(
      "wrong credentials do not sign anybody in",
      stillOnLogin ? "PASS" : "FAIL",
      stillOnLogin ? "stayed on /login" : `navigated to ${page.url()}`,
    );
    // The user must be told something. A silent no-op reads as a broken button.
    const saidSomething = /invalid|incorrect|wrong|could not|failed|error|try again/i.test(bodyText);
    record(
      "wrong credentials produce a visible message",
      saidSomething ? "PASS" : "FAIL",
      saidSomething ? "message shown" : "no feedback rendered",
    );

    // ---- 3. protected routes are protected ---------------------------------
    for (const route of ["/consult", "/settings", "/files", "/jobs", "/platform", "/settings/billing"]) {
      drain();
      await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      const url = page.url();
      const bounced = url.includes("/login");
      record(
        `signed-out ${route} redirects to login`,
        bounced ? "PASS" : "FAIL",
        bounced ? "-> /login" : `stayed at ${url}`,
      );
    }

    // ---- 4. nonsense URLs do not crash the app -----------------------------
    for (const route of ["/this-route-does-not-exist", "/en/nope/deeper", "/%20%20", "/consult/../../etc"]) {
      drain();
      const response = await page
        .goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" })
        .catch(() => null);
      await page.waitForTimeout(2000);
      const status = response ? response.status() : 0;
      const seenHere = drain();
      // 404 and a redirect are both fine. A 5xx is not.
      const ok = status < 500 && !seenHere.errors.some((e) => /hydration|Minified React/i.test(e));
      record(
        `nonsense route ${route} does not 5xx`,
        ok ? "PASS" : "FAIL",
        `status ${status}${seenHere.errors[0] ? ` | ${seenHere.errors[0]}` : ""}`,
      );
    }

    // ---- 5. browser back / forward ----------------------------------------
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    drain();
    await page.goBack({ waitUntil: "domcontentloaded" }).catch(() => {});
    await page.waitForTimeout(2500);
    await page.goForward({ waitUntil: "domcontentloaded" }).catch(() => {});
    await page.waitForTimeout(2500);
    const navSeen = drain();
    record(
      "back/forward navigation does not error",
      navSeen.errors.length ? "FAIL" : "PASS",
      navSeen.errors[0] || "clean",
    );

    // ---- 6. responsive: no horizontal overflow -----------------------------
    for (const vp of VIEWPORTS) {
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("form.w-72", { timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(1200);

      const metrics = await page.evaluate(() => ({
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
      }));
      // 2px of slack absorbs sub-pixel rounding on fractional device ratios.
      const overflow = metrics.scrollW - metrics.clientW;
      record(
        `no horizontal overflow at ${vp.name}`,
        overflow <= 2 ? "PASS" : "FAIL",
        `scrollW ${metrics.scrollW} vs clientW ${metrics.clientW}`,
      );

      // The form must remain usable, not merely present.
      const emailBox = await page.locator('form.w-72 input[type="email"]').boundingBox().catch(() => null);
      const fits = !!emailBox && emailBox.width > 80 && emailBox.x >= -1 && emailBox.x + emailBox.width <= vp.w + 2;
      record(
        `login form is usable at ${vp.name}`,
        fits ? "PASS" : "FAIL",
        emailBox ? `x=${Math.round(emailBox.x)} w=${Math.round(emailBox.width)}` : "email field not found",
      );
    }
    await page.setViewportSize({ width: 1440, height: 900 });

    // ---- 7. how far does signup get without a mailbox? ---------------------
    // Not an assertion about success: it establishes exactly where the
    // credential-free path ends, so the report can say so precisely.
    drain();
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("form.w-72", { timeout: 30000 });
    await page.waitForTimeout(1200);
    await page.locator('button[type="button"]:has-text("Create account")').first().click().catch(() => {});
    await page.waitForTimeout(1000);
    const probeEmail = `qa-probe-${Date.now()}@example.com`;
    await form.locator('input[type="email"]').fill(probeEmail);
    await form.locator('input[type="password"]').fill("TestUser#2026");
    await form.locator('button[type="submit"]').click().catch(() => {});
    await page.waitForTimeout(9000);
    const codeBox = await page.locator('input[placeholder="Verification code"]').count();
    const signupText = (await page.locator("body").innerText().catch(() => "")) || "";
    record(
      "signup reaches the verification-code step",
      codeBox > 0 ? "PASS" : "INFO",
      codeBox > 0
        ? "code step reached; completing it needs a readable mailbox"
        : signupText.replace(/\s+/g, " ").slice(0, 120),
    );

    if (codeBox > 0) {
      // A wrong code must be refused, and that IS testable without a mailbox.
      await page.locator('input[placeholder="Verification code"]').fill("000000");
      await form.locator('button[type="submit"]').click().catch(() => {});
      await page.waitForTimeout(6000);
      const blocked = page.url().includes("/login");
      record(
        "an incorrect verification code is refused",
        blocked ? "PASS" : "FAIL",
        blocked ? "stayed on /login" : `let in at ${page.url()}`,
      );
    }
  } catch (error) {
    record("suite completed without crashing", "FAIL", String(error).split("\n")[0].slice(0, 180));
  } finally {
    await browser.close();
  }

  const pass = results.filter((r) => r.status === "PASS").length;
  const fail = results.filter((r) => r.status === "FAIL").length;
  const info = results.filter((r) => r.status === "INFO").length;
  console.log(`\n===== qa-public: ${pass} passed, ${fail} failed, ${info} informational =====`);
  for (const r of results.filter((x) => x.status !== "PASS")) {
    console.log(`  ${r.status} ${r.name}: ${r.detail}`);
  }
  process.exit(fail === 0 ? 0 : 1);
})();
