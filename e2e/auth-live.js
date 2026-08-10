/**
 * Live authentication E2E, driven in a REAL Chrome window, with codes read from
 * a REAL inbox.
 *
 *   E2E_HEADED=1 node auth-live.js
 *
 * How this differs from auth-local.js: that one scrapes codes out of a
 * `convex logs` stream, which only ever worked because no mail provider was
 * configured â€” `authEmail.ts` logs the code from its CATCH block, so a code
 * reaches the logs only when sending FAILS. With SMTP delivering, the logs are
 * silent and that suite cannot complete. This one fetches the code over IMAP
 * (`get-code.py`), which also proves the mail actually left the building.
 *
 * Every account uses plus-addressing (akshat+authNNN@â€¦), so runs are isolated
 * but all the mail lands in one inbox we can read.
 *
 * Env:
 *   E2E_BASE_URL   default http://localhost:3000
 *   E2E_IMAP_USER  mailbox to read (also the plus-address base)
 *   E2E_IMAP_PASS  Gmail app password
 *   E2E_HEADED=1   show the browser (recommended - the point is to watch it)
 *   E2E_SLOWMO     ms between actions, default 400 so it is followable
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL || "http://localhost:3000";
const IMAP_USER = process.env.E2E_IMAP_USER || "";
const PYTHON =
  process.env.E2E_PYTHON ||
  path.join(__dirname, "..", "backend-python", ".venv", "Scripts", "python.exe");

const tag = String(Date.now()).slice(-6);
const [local, domain] = IMAP_USER.split("@");
const EMAIL = `${local}+auth${tag}@${domain}`;
const OTP_EMAIL = `${local}+otp${tag}@${domain}`;
const PW = "TestUser#2026";
const NEWPW = "NewPass#2026";

let verifyCode = "";
const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` - ${detail}` : ""}`);
};

/**
 * Pull the newest emailed code for `recipient`, refusing `exclude`.
 *
 * The exclusion matters: asking twice for the same address returns the FIRST
 * email's code if the second has not landed yet, so the reset step happily
 * replayed the sign-up code and every assertion still looked green.
 */
function codeFor(recipient, exclude = "", timeout = 120) {
  return execFileSync(
    PYTHON,
    [path.join(__dirname, "get-code.py"), recipient, String(timeout), exclude],
    { encoding: "utf8", env: process.env },
  ).trim();
}

/** Wait for the app to leave /login, rather than sleeping and hoping. */
async function waitSignedIn(page, ms = 25000) {
  try {
    await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: ms });
  } catch {
    /* caller records the failure with the URL and any form error */
  }
}

// The login page has two forms: password (w-72) and magic-code (w-64). Both
// contain input[type=email], so every locator must be scoped to one of them.
const pwForm = (page) => page.locator("form.w-72");
const otpForm = (page) => page.locator("form.w-64");
const submitPw = (page) => pwForm(page).locator('button[type="submit"]');
const switchTo = (page, text) =>
  page.locator(`button[type="button"]:has-text("${text}")`).first();

/** Whatever the form is complaining about. Without this a failure just reports a
 *  URL, which says the sign-in did not happen but never says why. */
async function errorText(page) {
  const alert = page.locator('p[role="alert"]').first();
  if (await alert.count()) {
    const text = (await alert.textContent().catch(() => "")) || "";
    if (text.trim()) return `| error: ${text.trim().slice(0, 120)}`;
  }
  return "";
}

/**
 * Sign out and land on a usable login form.
 *
 * Clicking the real sidebar button is the honest test, but `signOut()` is async
 * and a fixed sleep raced it: the session was still valid when we navigated, the
 * middleware bounced /login back to /, and the next `fill()` waited 30s for a
 * form that was never rendered. So we WAIT FOR THE FORM rather than for a clock,
 * and clear cookies as a fallback so one flaky sign-out cannot fail every later
 * assertion.
 */
async function gotoLogin(page) {
  const button = page.locator('button:has-text("Log out")');
  if (await button.count()) {
    await button.first().click().catch(() => {});
    await page.waitForURL(/\/login/, { timeout: 20000 }).catch(() => {});
  }

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  try {
    await page.waitForSelector('form.w-72 input[type="email"]', { timeout: 15000 });
    return;
  } catch {
    // Still authenticated. Cookies alone are not enough: Convex Auth keeps its
    // token in localStorage, so clearing only cookies left a half-signed-in
    // client that accepted the form and then silently refused the sign-in —
    // which showed up as an intermittent failure with NO error on the page.
    await page.context().clearCookies();
    await page
      .evaluate(() => {
        localStorage.clear();
        sessionStorage.clear();
      })
      .catch(() => {});
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('form.w-72 input[type="email"]', { timeout: 20000 });
  }
  // Let the Convex client finish initialising before typing into the form.
  await page.waitForTimeout(1500);
}

(async () => {
  if (!IMAP_USER) {
    console.error("E2E_IMAP_USER is required");
    process.exit(2);
  }

  const browser = await chromium.launch({
    headless: process.env.E2E_HEADED !== "1",
    slowMo: Number(process.env.E2E_SLOWMO || 400),
    args: ["--start-maximized"],
  });
  const page = await browser.newPage({ viewport: null });

  try {
    // ---- 1. SIGN UP + EMAIL VERIFICATION -----------------------------------
    console.log(`\n=== signing up as ${EMAIL} ===`);
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);

    await switchTo(page, "Create account").click();
    await pwForm(page).locator('input[type="email"]').fill(EMAIL);
    await pwForm(page).locator('input[type="password"]').fill(PW);
    await submitPw(page).click();
    await page.waitForTimeout(4000);

    const codeBox = pwForm(page).locator('input[placeholder="Verification code"]');
    record("sign-up asks for a verification code", (await codeBox.count()) > 0);

    if (await codeBox.count()) {
      const code = codeFor(EMAIL);
      verifyCode = code;
      console.log(`   code from inbox: ${code}`);
      record("verification code arrived by EMAIL", /^\d{6,8}$/.test(code), code);
      await codeBox.fill(code);
      await submitPw(page).click();
      await waitSignedIn(page);
      record(
        "verified and signed in",
        !page.url().includes("/login"),
        page.url(),
      );
    }

    // ---- 2. SIGN OUT, THEN PASSWORD SIGN-IN --------------------------------
    await gotoLogin(page);
    await pwForm(page).locator('input[type="email"]').fill(EMAIL);
    await pwForm(page).locator('input[type="password"]').fill(PW);
    await submitPw(page).click();
    await waitSignedIn(page);
    record(
      "password sign-in works",
      !page.url().includes("/login"),
      `${page.url()} ${await errorText(page)}`,
    );

    // ---- 3. FORGOT PASSWORD -> RESET ---------------------------------------
    await gotoLogin(page);
    await switchTo(page, "Forgot password?").click();
    await pwForm(page).locator('input[type="email"]').fill(EMAIL);
    await submitPw(page).click();
    await page.waitForTimeout(4000);

    const resetCode = codeFor(EMAIL, verifyCode);
    console.log(`   reset code from inbox: ${resetCode}`);
    record("password-reset code arrived by EMAIL", /^\d{6,8}$/.test(resetCode), resetCode);

    // The reset step labels its field "Reset code", NOT "Verification code" â€”
    // those are two different modes in auth-form.tsx, and there is no confirm
    // field. Guessing the wrong placeholder waits 30s for an input that is not
    // on the page.
    await pwForm(page).locator('input[placeholder="Reset code"]').fill(resetCode);
    await pwForm(page).locator('input[placeholder="New password"]').fill(NEWPW);
    await submitPw(page).click();
    await waitSignedIn(page);
    record(
      "password reset completed",
      !page.url().includes("/login"),
      `${page.url()} ${await errorText(page)}`,
    );

    // ---- 4. PASSWORDLESS EMAIL OTP -----------------------------------------
    await gotoLogin(page);
    await otpForm(page).locator('input[type="email"]').fill(OTP_EMAIL);
    await otpForm(page).locator('button[type="submit"]').click();
    await page.waitForTimeout(4000);

    const otp = codeFor(OTP_EMAIL);
    console.log(`   OTP from inbox: ${otp}`);
    record("magic-code arrived by EMAIL", /^\d{6,8}$/.test(otp), otp);

    // The magic-code form is TWO STEPS: after the address is submitted the email
    // input is REPLACED by the code input, so there is never a second input to
    // index into â€” `.nth(1)` waits forever. Target the placeholder instead.
    await otpForm(page).locator('input[placeholder="8-digit code"]').fill(otp);
    await otpForm(page).locator('button[type="submit"]').click();
    await waitSignedIn(page);
    record(
      "passwordless OTP sign-in works",
      !page.url().includes("/login"),
      `${page.url()} ${await errorText(page)}`,
    );

    // ---- 5. GOOGLE BUTTON ---------------------------------------------------
    await gotoLogin(page);
    const googleButton = page.locator('button:has-text("Continue with Google")');
    const googleVisible = (await googleButton.count()) > 0;
    record("Google button is shown", googleVisible, googleVisible ? "visible" : "HIDDEN");

    if (googleVisible) {
      // Click it for real and follow the redirect. We stop at Google's own page â€”
      // completing the consent needs a human password, but reaching accounts.google
      // with our client id proves the whole chain: button -> Convex signin route ->
      // Google, with a client id Google recognises. A wrong redirect URI or an
      // unknown client fails HERE, with Google's error page, which is exactly the
      // failure this test exists to catch.
      await googleButton.click();
      await page.waitForTimeout(9000);
      const url = page.url();
      const onGoogle = url.includes("accounts.google.com");
      record("clicking it reaches Google's sign-in", onGoogle, url.slice(0, 110));

      if (onGoogle) {
        const bodyText = (await page.textContent("body").catch(() => "")) || "";
        record(
          "Google accepts our client (no redirect_uri_mismatch / invalid client)",
          !/redirect_uri_mismatch|invalid_client|Access blocked|doesn't comply/i.test(bodyText),
          (bodyText.match(/redirect_uri_mismatch|invalid_client|Access blocked/i) || [
            "clean",
          ])[0],
        );
      }
    }

    console.log("\n(browser stays open 15s so you can look at it)");
    await page.waitForTimeout(15000);
  } catch (error) {
    record("suite completed without crashing", false, String(error).slice(0, 200));
  } finally {
    await browser.close();
  }

  const passed = results.filter((r) => r.ok).length;
  console.log(`\n===== auth-live: ${passed}/${results.length} passed =====`);
  for (const r of results.filter((x) => !x.ok)) console.log(`  - ${r.name}: ${r.detail}`);
  process.exit(passed === results.length ? 0 : 1);
})();

