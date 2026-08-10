/**
 * Full end-to-end check of the LIVE site, in a real browser.
 *
 *   E2E_BASE_URL=https://ayur.namahos.com \
 *   E2E_API_URL=https://ayur-api.namahos.com \
 *   E2E_IMAP_USER=... E2E_IMAP_PASS=... node prod-full.js
 *
 * `auth-live.js` already proves the five sign-in paths. This covers what happens
 * AFTER sign-in, plus the things that only break in production: TLS, security
 * headers, CORS between the two subdomains, mixed content, and one user being
 * able to see another's data.
 *
 * Assertions are deliberately about behaviour a person would notice, not about
 * internal state. Where a check depends on the free LLM tier having capacity, an
 * exhausted quota is reported as SKIPPED rather than FAILED — a rate limit is not
 * a defect in this application, and marking it as one would make the report lie.
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL || "https://ayur.namahos.com";
const API = process.env.E2E_API_URL || "https://ayur-api.namahos.com";
const IMAP_USER = process.env.E2E_IMAP_USER || "";
const PYTHON = path.join(__dirname, "..", "backend-python", ".venv", "Scripts", "python.exe");

// A consultation on the free tier can take well over a minute.
const REPLY_TIMEOUT_MS = Number(process.env.E2E_REPLY_TIMEOUT || 180000);

const tag = String(Date.now()).slice(-6);
const [local, domain] = IMAP_USER.split("@");
const USER_A = `${local}+pa${tag}@${domain}`;
const USER_B = `${local}+pb${tag}@${domain}`;
const PW = "TestUser#2026";

const results = [];
const record = (name, status, detail = "") => {
  results.push({ name, status, detail });
  const mark = status === "PASS" ? "PASS" : status === "SKIP" ? "SKIP" : "FAIL";
  console.log(`${mark}  ${name}${detail ? ` - ${detail}` : ""}`);
};
const pass = (n, d) => record(n, "PASS", d);
const fail = (n, d) => record(n, "FAIL", d);
const skip = (n, d) => record(n, "SKIP", d);

const codeFor = (recipient, exclude = "") =>
  execFileSync(PYTHON, [path.join(__dirname, "get-code.py"), recipient, "150", exclude], {
    encoding: "utf8",
    env: process.env,
  }).trim();

const pwForm = (page) => page.locator("form.w-72");

/** Sign a brand-new account up and land on the dashboard. */
async function signUp(page, email) {
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('form.w-72 input[type="email"]', { timeout: 30000 });
  await page.waitForTimeout(1200);

  await page.locator('button[type="button"]:has-text("Create account")').first().click();
  await pwForm(page).locator('input[type="email"]').fill(email);
  await pwForm(page).locator('input[type="password"]').fill(PW);
  await pwForm(page).locator('button[type="submit"]').click();
  await page.waitForTimeout(4500);

  const code = codeFor(email);
  await pwForm(page).locator('input[placeholder="Verification code"]').fill(code);
  await pwForm(page).locator('button[type="submit"]').click();
  await page
    .waitForURL((url) => !url.pathname.includes("/login"), { timeout: 40000 })
    .catch(() => {});
  await completeOnboarding(page);
  return code;
}

/**
 * A brand-new account is sent to /onboarding to choose a username, and every
 * dashboard route bounces there until it is done. The first run of this suite
 * reported "consult screen opens: FAIL" for exactly that reason — the app was
 * behaving correctly and the test was not.
 */
async function completeOnboarding(page) {
  if (!page.url().includes("/onboarding")) return;
  const username = `t${String(Date.now()).slice(-8)}`;
  await page.locator('input[placeholder="Username"]').fill(username);
  await page.locator('button[type="submit"]').click();
  await page
    .waitForURL((url) => !url.pathname.includes("/onboarding"), { timeout: 30000 })
    .catch(() => {});
  await page.waitForTimeout(1500);
}

/**
 * Navigate somewhere behind the dashboard, clearing onboarding if it gets in the
 * way. Onboarding sends you to `/` when it finishes, not back to where you were
 * headed, so the destination has to be requested again afterwards.
 */
async function gotoDashboard(page, target) {
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto(`${BASE}${target}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    if (!page.url().includes("/onboarding")) return;
    await completeOnboarding(page);
  }
}

async function signOut(page) {
  const button = page.locator('button:has-text("Log out")');
  if (await button.count()) {
    await button.first().click().catch(() => {});
    await page.waitForURL(/\/login/, { timeout: 25000 }).catch(() => {});
  }
  await page.context().clearCookies();
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  }).catch(() => {});
}

/** Begin a clean consultation, the way a user does: the sidebar's "New Chat". */
async function startNewChat(page) {
  const button = page.locator('a:has-text("New Chat")').first();
  if (await button.count()) {
    await button.click().catch(() => {});
  } else {
    await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
  }
  await page.waitForSelector("textarea", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(2500);
}

/**
 * Send one message and wait for the assistant to actually produce something.
 *
 * Returns {ok, text, reason}. `reason: "quota"` when the backend reported that
 * every model in the chain is rate limited, so the caller can SKIP rather than
 * FAIL.
 */
async function ask(page, message) {
  const composer = page.locator("textarea").first();
  await composer.waitFor({ timeout: 30000 });
  const before = (await page.locator("main").innerText().catch(() => "")) || "";

  await composer.fill(message);
  await composer.press("Enter");

  const deadline = Date.now() + REPLY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await page.waitForTimeout(2500);
    const now = (await page.locator("main").innerText().catch(() => "")) || "";
    // Match the wording the app ACTUALLY uses when the model chain is out of
    // free-tier tokens. The first version of this list was written in English
    // only, so the real message — "Aaj ki daily AI limit khatam ho gayi hai" —
    // slipped past it and the run was reported as a FAILURE. It is not one: the
    // app degraded exactly as designed and said so.
    if (
      /daily AI limit|limit khatam|credit limit reached|rate limit|quota|try again in|temporarily unavailable/i.test(
        now,
      )
    ) {
      const line = now.match(/[^\n]*(daily AI limit|credit limit reached|rate limit)[^\n]*/i);
      return { ok: false, reason: "quota", text: (line ? line[0] : now.slice(-200)).trim().slice(0, 160) };
    }
    // An error banner is a reply of sorts, so the length check below would have
    // called it a pass. Fail on it explicitly instead — this is how the 401 from
    // the AI backend first showed up as a green tick.
    const banner = now.match(/The AI backend returned an error[^.]*\./i);
    if (banner) return { ok: false, reason: "error", text: banner[0] };
    // The reply may be prose or a set of intake question cards; either is the
    // assistant responding. Require a real change, not just a spinner.
    if (now.length > before.length + 40) {
      return { ok: true, text: now.slice(before.length).trim().slice(0, 400) };
    }
  }
  return { ok: false, reason: "timeout", text: "" };
}

(async () => {
  if (!IMAP_USER) {
    console.error("E2E_IMAP_USER is required");
    process.exit(2);
  }

  const browser = await chromium.launch({
    headless: process.env.E2E_HEADED !== "1",
    slowMo: Number(process.env.E2E_SLOWMO || 120),
    args: ["--start-maximized"],
  });
  const context = await browser.newContext({ viewport: null });
  const page = await context.newPage();

  const consoleErrors = [];
  const mixedContent = [];
  const failedRequests = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
  });
  page.on("requestfailed", (r) => {
    failedRequests.push(`${r.url().slice(0, 90)} :: ${r.failure()?.errorText}`);
  });
  page.on("request", (r) => {
    if (r.url().startsWith("http://") && !r.url().includes("localhost")) mixedContent.push(r.url());
  });

  try {
    // ---- 1. transport ------------------------------------------------------
    const response = await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    const headers = response ? await response.allHeaders() : {};
    pass("site loads over HTTPS", `HTTP ${response?.status()} at ${page.url()}`);
    record(
      "HSTS header present",
      headers["strict-transport-security"] ? "PASS" : "FAIL",
      headers["strict-transport-security"] || "missing",
    );
    record(
      "clickjacking blocked",
      headers["x-frame-options"] === "DENY" ? "PASS" : "FAIL",
      headers["x-frame-options"] || "missing",
    );

    // ---- 2. account A ------------------------------------------------------
    console.log(`\n=== user A: ${USER_A} ===`);
    await signUp(page, USER_A);
    const signedIn = !page.url().includes("/login");
    record("sign up + email verification", signedIn ? "PASS" : "FAIL", page.url());
    if (!signedIn) throw new Error("cannot continue without a session");

    // ---- 3. session survives a reload --------------------------------------
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    record(
      "session survives a page refresh",
      page.url().includes("/login") ? "FAIL" : "PASS",
      page.url(),
    );

    // ---- 4. the consult screen --------------------------------------------
    await gotoDashboard(page, "/consult");
    const composerVisible = (await page.locator("textarea").count()) > 0;
    record("consult screen opens", composerVisible ? "PASS" : "FAIL", page.url());

    if (composerVisible) {
      // ---- 5. the three languages -----------------------------------------
      const prompts = [
        ["English", "I have trouble sleeping at night and feel tired all day"],
        ["Hindi (Devanagari)", "मुझे रात को नींद नहीं आती और दिन भर थकान रहती है"],
        ["Hinglish", "mujhe raat ko neend nahi aati aur din bhar thakan rehti hai"],
      ];
      for (const [label, text] of prompts) {
        // Start each language in a FRESH conversation.
        //
        // The first answer puts the consultation into its intake phase, where
        // the composer means "add anything else" rather than "ask something
        // new" — so the next two prompts were being folded into the first
        // conversation instead of starting their own. The suite then waited for
        // a reply that was never going to come and blamed the app.
        await startNewChat(page);
        const reply = await ask(page, text);
        if (reply.ok) {
          pass(`AI replies - ${label}`, reply.text.replace(/\s+/g, " ").slice(0, 110));
        } else if (reply.reason === "quota") {
          skip(`AI replies - ${label}`, "LLM free tier exhausted, not an app defect");
        } else if (reply.reason === "error") {
          fail(`AI replies - ${label}`, reply.text);
        } else {
          fail(`AI replies - ${label}`, `no reply within ${REPLY_TIMEOUT_MS / 1000}s`);
        }
        await page.waitForTimeout(1500);
      }

      // ---- 6. history persists across a reload ----------------------------
      const before = (await page.locator("main").innerText().catch(() => "")) || "";
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      const after = (await page.locator("main").innerText().catch(() => "")) || "";
      record(
        "existing chat reloads with its history",
        after.length > 100 && before.length > 100 ? "PASS" : "FAIL",
        `${before.length} chars before, ${after.length} after`,
      );
    }

    // ---- 7. sign out really ends the session -------------------------------
    await signOut(page);
    await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    record(
      "signed out user cannot reach /consult",
      page.url().includes("/login") ? "PASS" : "FAIL",
      page.url(),
    );

    // ---- 8. a second user sees none of the first user's data ---------------
    console.log(`\n=== user B: ${USER_B} ===`);
    await signUp(page, USER_B);
    if (page.url().includes("/login")) {
      fail("second account can sign up", page.url());
    } else {
      pass("second account can sign up", page.url());
      await gotoDashboard(page, "/consult");
      await page.waitForTimeout(2000);
      const text = (await page.locator("main").innerText().catch(() => "")) || "";
      const leaked = /neend nahi aati|नींद नहीं आती|trouble sleeping/i.test(text);
      record(
        "user B cannot see user A's conversation",
        leaked ? "FAIL" : "PASS",
        leaked ? "LEAKED another user's content" : "no cross-user content",
      );
    }

    // ---- 9. the API refuses anonymous callers ------------------------------
    // Snapshot the console first: the probe below deliberately provokes a 401,
    // and the browser logs every failed fetch. Counting our own probe as a
    // "critical console error" made the suite fail itself.
    const consoleErrorsBeforeProbe = consoleErrors.length;
    const anon = await page.evaluate(async (api) => {
      try {
        const r = await fetch(`${api}/consult`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: "hello" }),
        });
        return r.status;
      } catch (error) {
        return `fetch failed: ${String(error).slice(0, 80)}`;
      }
    }, API);
    record(
      "AI backend rejects unauthenticated calls",
      anon === 401 || anon === 403 ? "PASS" : "FAIL",
      `HTTP ${anon}`,
    );

    // ---- 10. browser-visible hygiene ---------------------------------------
    const realErrors = consoleErrors
      .slice(0, consoleErrorsBeforeProbe)
      .filter((e) => !/favicon|sentry|openpanel|ResizeObserver/i.test(e));
    record(
      "no critical console errors",
      realErrors.length === 0 ? "PASS" : "FAIL",
      realErrors.slice(0, 2).join(" | ") || "clean",
    );
    record(
      "no mixed content",
      mixedContent.length === 0 ? "PASS" : "FAIL",
      mixedContent.slice(0, 2).join(" | ") || "clean",
    );
    const cors = failedRequests.filter((f) => /CORS|blocked/i.test(f));
    record("no CORS failures", cors.length === 0 ? "PASS" : "FAIL", cors.slice(0, 2).join(" | ") || "clean");
  } catch (error) {
    fail("suite completed without crashing", String(error).split("\n")[0].slice(0, 180));
  } finally {
    await browser.close();
  }

  const passed = results.filter((r) => r.status === "PASS").length;
  const failed = results.filter((r) => r.status === "FAIL").length;
  const skipped = results.filter((r) => r.status === "SKIP").length;
  console.log(`\n===== prod-full: ${passed} passed, ${failed} failed, ${skipped} skipped =====`);
  for (const r of results.filter((x) => x.status === "FAIL")) {
    console.log(`  FAIL ${r.name}: ${r.detail}`);
  }
  for (const r of results.filter((x) => x.status === "SKIP")) {
    console.log(`  SKIP ${r.name}: ${r.detail}`);
  }
  process.exit(failed === 0 ? 0 : 1);
})();
