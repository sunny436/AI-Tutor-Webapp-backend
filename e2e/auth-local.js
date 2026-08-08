/**
 * Full authentication E2E against a local dev stack.
 *
 * The older p2-auth.js targets a decommissioned VM and pulls codes over SSH. This
 * one drives http://localhost:3000 and reads codes from a `convex logs` stream, so
 * it runs on a developer machine with no mail provider configured.
 *
 * Setup:
 *   1. cd apps/app && next dev -p 3000
 *   2. cd packages/backend && npx convex logs > <LOG_FILE>
 *   3. E2E_LOG_FILE=<LOG_FILE> node e2e/auth-local.js
 *
 * Env: E2E_BASE_URL, E2E_LOG_FILE, E2E_HEADED=1
 */
const fs = require("node:fs");
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL || "http://localhost:3000";
const LOG_FILE = process.env.E2E_LOG_FILE;
const ts = Date.now();
const EMAIL = `authtest${ts}@example.com`;
const PW = "TestUser#2026";
const NEWPW = "NewPass#2026";
const CHANGED_PW = "Changed#2026";
const OTP_EMAIL = `otptest${ts}@example.com`;

const results = [];
const consoleErrors = [];
let currentPage = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function step(name, fn) {
  try {
    const detail = await fn();
    results.push([true, name, detail || ""]);
    console.log(`PASS  ${name}${detail ? ` - ${detail}` : ""}`);
  } catch (e) {
    const msg = String(e.message).split("\n")[0];
    let context = "";
    if (currentPage) {
      try {
        const buttons = await currentPage.locator("button").allTextContents();
        context = ` [url=${currentPage.url()} buttons=${JSON.stringify(buttons.slice(0, 8))}]`;
      } catch (_) {}
    }
    results.push([false, name, msg + context]);
    console.log(`FAIL  ${name} - ${msg}${context}`);
  }
}

// --- selectors -------------------------------------------------------------
// The login page hosts two independent forms: the password form (w-72) and the
// magic-code form (w-64). Both contain an input[type=email], so every locator is
// scoped to one of them. Mode switches are <button type="button">, submits are
// <button type="submit">, which disambiguates same-text buttons.
const pwForm = (page) => page.locator("form.w-72");
const otpForm = (page) => page.locator("form.w-64");
const switchTo = (page, text) =>
  page.locator(`button[type="button"]:has-text("${text}")`).first();
const submitPw = (page) => pwForm(page).locator('button[type="submit"]');

/**
 * Everything behind the login page renders from reactive Convex queries over a
 * WebSocket that can take several seconds to establish on a cold context, so
 * post-login waits are generous.
 */
const SLOW = 45000;

/** Navigate and wait for hydration - clicks before it are silently dropped. */
async function goto(page, path) {
  await page.goto(BASE + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(400);
}

function prepare(page) {
  page.setDefaultTimeout(SLOW);
  return page;
}

/**
 * Codes are printed by convex/email.ts when no mail provider is configured:
 *   [email] NOT DELIVERED. Configure RESEND_API_KEY or SMTP_HOST. Code for <to>: <code>
 * Always take the LAST match so a resend supersedes the original.
 */
async function getCode(email, { since = 0 } = {}) {
  if (!LOG_FILE) throw new Error("E2E_LOG_FILE not set");
  const re = new RegExp(`Code for ${email.replace(/[.+]/g, "\\$&")}:\\s*(\\d{6,8})`, "g");
  for (let i = 0; i < 40; i++) {
    if (fs.existsSync(LOG_FILE)) {
      const text = fs.readFileSync(LOG_FILE, "utf8").slice(since);
      const matches = [...text.matchAll(re)];
      if (matches.length) return matches[matches.length - 1][1];
    }
    await sleep(1500);
  }
  throw new Error(`no code found for ${email}`);
}

const logSize = () => (LOG_FILE && fs.existsSync(LOG_FILE) ? fs.statSync(LOG_FILE).size : 0);

async function alertText(scope) {
  const alert = scope.locator('p[role="alert"]').first();
  if (await alert.count()) return ((await alert.textContent()) ?? "").trim();
  return "";
}

async function signInWith(page, email, password) {
  await goto(page, "/login");
  await pwForm(page).locator('input[type="email"]').fill(email);
  await pwForm(page).locator('input[type="password"]').fill(password);
  await submitPw(page).click();
}

async function logOut(page) {
  await goto(page, "/settings");
  // The sidebar (which holds Log out) only renders once the Convex socket is up.
  const button = page.locator('button:has-text("Log out")');
  await button.first().waitFor({ state: "visible", timeout: SLOW }).catch(() => {});
  if (await button.count()) {
    await button.first().click();
    await page.waitForURL(/\/login/, { timeout: SLOW });
  }
}

(async () => {
  const browser = await chromium.launch({ headless: !process.env.E2E_HEADED });
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = prepare(await context.newPage());
  currentPage = page;
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });

  // ---------------------------------------------------------------- guards
  await step("unauthenticated /consult redirects to /login?redirect=/consult", async () => {
    await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/login/, { timeout: 20000 });
    const url = new URL(page.url());
    if (url.searchParams.get("redirect") !== "/consult") {
      throw new Error(`redirect param was ${url.searchParams.get("redirect")}`);
    }
    return url.pathname + url.search;
  });

  // ---------------------------------------------------------------- sign-up
  await step("sign-up rejects a weak password client-side", async () => {
    await goto(page, "/login");
    await switchTo(page, "Create account").click();
    await pwForm(page).locator('input[type="email"]').fill(EMAIL);
    await pwForm(page).locator('input[type="password"]').fill("weak");
    await submitPw(page).click();
    await page.waitForTimeout(800);
    const msg = await alertText(pwForm(page));
    if (!/Password needs/i.test(msg)) throw new Error(`got: ${msg || "(none)"}`);
    return msg;
  });

  const signupMark = logSize();
  await step("sign-up creates an unverified account and asks for a code", async () => {
    await pwForm(page).locator('input[type="password"]').fill(PW);
    await submitPw(page).click();
    await page.waitForSelector('input[placeholder="Verification code"]', { timeout: 30000 });
  });

  await step("duplicate sign-up is reported clearly", async () => {
    await goto(page, "/login");
    await switchTo(page, "Create account").click();
    await pwForm(page).locator('input[type="email"]').fill(EMAIL);
    await pwForm(page).locator('input[type="password"]').fill(PW);
    await submitPw(page).click();
    await page.waitForTimeout(3000);
    const msg = await alertText(pwForm(page));
    if (!/already exists/i.test(msg)) throw new Error(`got: ${msg || "(none)"}`);
    return msg;
  });

  await step("signing in before verifying routes to the code step (not a silent no-op)", async () => {
    await signInWith(page, EMAIL, PW);
    await page.waitForSelector('input[placeholder="Verification code"]', { timeout: 30000 });
  });

  await step("a wrong verification code shows an error", async () => {
    await pwForm(page).locator('input[placeholder="Verification code"]').fill("00000000");
    await submitPw(page).click();
    await page.waitForTimeout(3500);
    const msg = await alertText(pwForm(page));
    if (!/valid|expired/i.test(msg)) throw new Error(`got: ${msg || "(none)"}`);
    return msg;
  });

  await step("the correct verification code signs the user in", async () => {
    const code = await getCode(EMAIL, { since: signupMark });
    await pwForm(page).locator('input[placeholder="Verification code"]').fill(code);
    await submitPw(page).click();
    await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 30000 });
    return `code ${code}`;
  });

  await step("new user is sent to onboarding, then reaches the dashboard", async () => {
    await page.waitForTimeout(2000);
    if (/onboarding/.test(page.url())) {
      // The onboarding form renders `null` until `users.getUser` resolves over the
      // Convex socket, so wait for the field rather than a fixed delay.
      await page.waitForSelector('input[placeholder="Username"]', { timeout: SLOW });
      await page.fill('input[placeholder="Username"]', `auth${String(ts).slice(-6)}`);
      await page.click('button:has-text("Continue")');
      await page.waitForURL((u) => !/onboarding/.test(u.toString()), { timeout: SLOW });
    }
    await goto(page, "/");
    if (/login|onboarding/.test(page.url())) throw new Error(`stuck at ${page.url()}`);
    return page.url();
  });

  // ------------------------------------------------------------ change password
  await step("change password rejects a wrong current password", async () => {
    await goto(page, "/settings");
    await page.waitForSelector('input[placeholder="Current password"]', { timeout: 30000 });
    await page.fill('input[placeholder="Current password"]', "Wrong#9999");
    await page.fill('input[placeholder="New password"]', CHANGED_PW);
    await page.fill('input[placeholder="Confirm new password"]', CHANGED_PW);
    await page.click('button:has-text("Change password")');
    await page.waitForTimeout(3500);
    const msg = await alertText(page);
    if (!/current password/i.test(msg)) throw new Error(`got: ${msg || "(none)"}`);
    return msg;
  });

  await step("change password succeeds with the correct current password", async () => {
    await page.fill('input[placeholder="Current password"]', PW);
    await page.fill('input[placeholder="New password"]', CHANGED_PW);
    await page.fill('input[placeholder="Confirm new password"]', CHANGED_PW);
    await page.click('button:has-text("Change password")');
    await page.waitForTimeout(4000);
    if (!/Password changed/i.test(await page.textContent("body"))) {
      throw new Error("no success confirmation");
    }
  });

  // ------------------------------------------------------------------ logout
  await step("logout clears the session and protected routes bounce", async () => {
    await logOut(page);
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/login/, { timeout: 20000 });
  });

  await step("the old password is rejected after the change", async () => {
    await signInWith(page, EMAIL, PW);
    await page.waitForTimeout(3500);
    const msg = await alertText(pwForm(page));
    if (!/isn't right|not right/i.test(msg)) throw new Error(`got: ${msg || "(none)"}`);
    return msg;
  });

  await step("the changed password signs in", async () => {
    await signInWith(page, EMAIL, CHANGED_PW);
    await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 30000 });
    return page.url();
  });

  // ------------------------------------------------------------- reset flow
  await step("forgot password for an unknown email does not crash or leak", async () => {
    await logOut(page);
    await goto(page, "/login");
    await switchTo(page, "Forgot password?").click();
    await pwForm(page).locator('input[type="email"]').fill(`nobody${ts}@example.com`);
    await submitPw(page).click();
    await page.waitForSelector('input[placeholder="Reset code"]', { timeout: 25000 });
    const body = await page.textContent("body");
    if (!/If an account exists/i.test(body)) throw new Error("generic message missing");
    if (/InvalidAccountId|Server Error/i.test(body)) throw new Error("raw error leaked");
  });

  const resetMark = logSize();
  await step("password reset: request -> code -> new password -> signed in", async () => {
    await goto(page, "/login");
    await switchTo(page, "Forgot password?").click();
    await pwForm(page).locator('input[type="email"]').fill(EMAIL);
    await submitPw(page).click();
    await page.waitForSelector('input[placeholder="Reset code"]', { timeout: 25000 });

    // The resend control is a sibling of the form, not inside it.
    const resend = page.locator('button[type="button"]:has-text("Resend code in")');
    const cooldown = (await resend.count()) ? ((await resend.textContent()) ?? "").trim() : "";

    const code = await getCode(EMAIL, { since: resetMark });
    await pwForm(page).locator('input[placeholder="Reset code"]').fill(code);
    await pwForm(page).locator('input[placeholder="New password"]').fill(NEWPW);
    await submitPw(page).click();
    await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 30000 });
    if (!cooldown) throw new Error("resend cooldown button missing");
    return `code ${code}; ${cooldown}`;
  });

  await step("the password set by reset works on a fresh sign-in", async () => {
    await logOut(page);
    await signInWith(page, EMAIL, NEWPW);
    await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 30000 });
    return page.url();
  });

  // ------------------------------------------------------------- remember me
  await step("remember-me unchecked yields a session cookie", async () => {
    await logOut(page);
    await goto(page, "/login");
    await pwForm(page).locator('input[type="checkbox"]').uncheck();
    await pwForm(page).locator('input[type="email"]').fill(EMAIL);
    await pwForm(page).locator('input[type="password"]').fill(NEWPW);
    await submitPw(page).click();
    await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 30000 });

    const cookies = await context.cookies();
    const jwt = cookies.find((c) => c.name.includes("convexAuthJWT"));
    if (!jwt) throw new Error("no auth cookie set");
    if (jwt.expires !== -1) throw new Error(`expected session cookie, got expires=${jwt.expires}`);
    const remember = cookies.find((c) => c.name === "rememberMe");
    if (remember?.value !== "0") throw new Error(`rememberMe=${remember?.value}`);
    return "session cookie (no expiry)";
  });

  await step("remember-me checked yields a persistent cookie", async () => {
    const ctx2 = await browser.newContext();
    const p2 = prepare(await ctx2.newPage());
    const previous = currentPage;
    currentPage = p2;
    try {
      await goto(p2, "/login");
      await pwForm(p2).locator('input[type="checkbox"]').check();
      await pwForm(p2).locator('input[type="email"]').fill(EMAIL);
      await pwForm(p2).locator('input[type="password"]').fill(NEWPW);
      await submitPw(p2).click();
      await p2.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 30000 });
      const jwt = (await ctx2.cookies()).find((c) => c.name.includes("convexAuthJWT"));
      if (!jwt) throw new Error("no auth cookie set");
      if (jwt.expires === -1) throw new Error("expected a persistent cookie");
      return `expires in ${Math.round((jwt.expires * 1000 - Date.now()) / 86400000)}d`;
    } finally {
      currentPage = previous;
      await ctx2.close();
    }
  });

  // --------------------------------------------------------------- redirect
  await step("post-login redirect returns to the originally requested page", async () => {
    const ctx3 = await browser.newContext();
    const p3 = prepare(await ctx3.newPage());
    const previous = currentPage;
    currentPage = p3;
    try {
      await p3.goto(`${BASE}/consult`, { waitUntil: "networkidle" });
      await p3.waitForURL(/\/login/, { timeout: 20000 });
      await p3.waitForTimeout(400);
      await pwForm(p3).locator('input[type="email"]').fill(EMAIL);
      await pwForm(p3).locator('input[type="password"]').fill(NEWPW);
      await submitPw(p3).click();
      await p3.waitForURL(/\/consult/, { timeout: 30000 });
      return p3.url();
    } finally {
      currentPage = previous;
      await ctx3.close();
    }
  });

  // -------------------------------------------------------------- OTP flow
  await step("magic-code sign-in: wrong code errors, correct code signs in", async () => {
    const ctx4 = await browser.newContext();
    const p4 = prepare(await ctx4.newPage());
    const previous = currentPage;
    currentPage = p4;
    const otpMark = logSize();
    try {
      await goto(p4, "/login");
      await otpForm(p4).locator('input[type="email"]').fill(OTP_EMAIL);
      await otpForm(p4).locator('button[type="submit"]').click();
      await p4.waitForSelector('input[placeholder="8-digit code"]', { timeout: 30000 });

      await otpForm(p4).locator('input[placeholder="8-digit code"]').fill("00000000");
      await otpForm(p4).locator('button[type="submit"]').click();
      await p4.waitForTimeout(4000);
      const msg = await alertText(otpForm(p4));
      if (!/valid|expired/i.test(msg)) throw new Error(`wrong OTP not reported: ${msg || "(none)"}`);

      const code = await getCode(OTP_EMAIL, { since: otpMark });
      await otpForm(p4).locator('input[placeholder="8-digit code"]').fill(code);
      await otpForm(p4).locator('button[type="submit"]').click();
      await p4.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 30000 });
      return `rejected bad code, accepted ${code}`;
    } finally {
      currentPage = previous;
      await ctx4.close();
    }
  });

  await browser.close();

  const passed = results.filter((r) => r[0]).length;
  console.log(`\n========= AUTH E2E: ${passed}/${results.length} =========`);
  for (const [ok, name, detail] of results) {
    console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` - ${detail}` : ""}`);
  }
  const relevant = consoleErrors.filter((e) => !/favicon|404|Download the React/i.test(e));
  console.log(`\nconsole errors: ${relevant.length}`);
  for (const e of relevant.slice(0, 10)) console.log(`  - ${e.slice(0, 200)}`);
  process.exit(passed === results.length ? 0 : 1);
})().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});

