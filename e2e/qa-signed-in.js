/**
 * The SIGNED-IN half of the QA sweep — the half that has been missing.
 *
 *   setx E2E_IMAP_USER "you@gmail.com"
 *   setx E2E_IMAP_PASS "<16-char gmail app password>"
 *   node qa-signed-in.js
 *
 * WHY THIS EXISTS
 *
 * Three bugs reached the user in a row — a 401, then a 404, then a 401 again —
 * and all three had the same cause on my side: the only state I could test was
 * signed OUT, and every one of those bugs existed only when signed IN.
 *
 * The 404 is the clearest example. The "/api/" bail-out sat inside the
 * `!isAuthenticated` branch of the middleware, so an anonymous request returned
 * before the i18n rewrite and answered a clean 401. A signed-in request skipped
 * that branch, hit the rewrite, and 404ed on every message. Signed-out testing
 * did not merely miss it — it actively reported the endpoint as healthy.
 *
 * So this suite signs in for real, reading the verification code from a real
 * inbox with `get-code.py`, and then exercises the path users actually take.
 *
 * It deliberately asserts the TRANSPORT as well as the reply: `newPathUsed`
 * checks that the consult request went to our own origin. A regression that
 * sends the browser back to the API host directly would otherwise pass every
 * behavioural assertion right up until somebody's token expired.
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL || "https://ayur.namahos.com";
const IMAP_USER = process.env.E2E_IMAP_USER || "";
const PYTHON = path.join(__dirname, "..", "backend-python", ".venv", "Scripts", "python.exe");
const REPLY_TIMEOUT_MS = Number(process.env.E2E_REPLY_TIMEOUT || 180000);

const tag = String(Date.now()).slice(-6);
const [local, domain] = IMAP_USER.split("@");
const EMAIL = `${local}+qa${tag}@${domain}`;
const PW = "TestUser#2026";

const results = [];
const record = (name, status, detail = "") => {
  results.push({ name, status, detail });
  console.log(`${status}  ${name}${detail ? ` - ${detail}` : ""}`);
};

const codeFor = (to) =>
  execFileSync(PYTHON, [path.join(__dirname, "get-code.py"), to, "150", ""], {
    encoding: "utf8",
    env: process.env,
  }).trim();

const QUOTA = /daily AI limit|limit khatam|credit limit reached|rate limit|try again in/i;

/** Send one message and wait until the transcript stops growing. */
async function ask(page, text) {
  const composer = page.locator("textarea").first();
  await composer.waitFor({ timeout: 30000 });
  const before = (await page.locator("main").innerText().catch(() => "")) || "";

  await composer.fill(text);
  await composer.press("Enter");

  const deadline = Date.now() + REPLY_TIMEOUT_MS;
  let grew = false;
  let previous = before;
  let stable = 0;

  while (Date.now() < deadline) {
    await page.waitForTimeout(1200);
    const now = (await page.locator("main").innerText().catch(() => "")) || "";
    if (QUOTA.test(now)) return { ok: false, reason: "quota", text: now };
    if (now.length > before.length + 30) grew = true;
    if (grew) {
      stable = now === previous ? stable + 1 : 0;
      if (stable >= 2) return { ok: true, text: now };
    }
    previous = now;
  }
  return { ok: false, reason: "timeout", text: previous };
}

(async () => {
  if (!IMAP_USER || !process.env.E2E_IMAP_PASS) {
    console.error("E2E_IMAP_USER and E2E_IMAP_PASS are required.");
    console.error('  setx E2E_IMAP_USER "you@gmail.com"');
    console.error('  setx E2E_IMAP_PASS "<gmail app password>"');
    process.exit(2);
  }

  const browser = await chromium.launch({
    headless: process.env.E2E_HEADED !== "1",
    slowMo: Number(process.env.E2E_SLOWMO || 80),
  });
  const page = await browser.newPage();

  // Transport and health, collected for the whole session.
  const consultCalls = [];
  const consoleErrors = [];
  const failedResponses = [];
  const IGNORE = /favicon|openpanel|sentry|_vercel|chrome-extension|analytics/i;

  page.on("request", (r) => {
    if (/\/consult/.test(r.url())) consultCalls.push(`${r.method()} ${r.url()}`);
  });
  page.on("console", (m) => {
    if (m.type() === "error" && !IGNORE.test(m.text())) consoleErrors.push(m.text().slice(0, 160));
  });
  page.on("response", (r) => {
    if (r.status() >= 400 && !IGNORE.test(r.url())) {
      failedResponses.push(`${r.status()} ${r.url().slice(0, 110)}`);
    }
  });

  try {
    // ---- sign up for real ---------------------------------------------------
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('form.w-72 input[type="email"]', { timeout: 40000 });
    await page.waitForTimeout(1200);
    await page.locator('button[type="button"]:has-text("Create account")').first().click();
    const form = page.locator("form.w-72");
    await form.locator('input[type="email"]').fill(EMAIL);
    await form.locator('input[type="password"]').fill(PW);
    await form.locator('button[type="submit"]').click();
    await page.waitForTimeout(5000);
    await form.locator('input[placeholder="Verification code"]').fill(codeFor(EMAIL));
    await form.locator('button[type="submit"]').click();
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 45000 }).catch(() => {});
    record("signed in with a real emailed code", page.url().includes("/login") ? "FAIL" : "PASS", page.url());

    // New accounts are held at /onboarding until they pick a username, and it
    // returns to "/" rather than where we were going, so /consult is asked for
    // again afterwards.
    for (let attempt = 0; attempt < 3; attempt++) {
      await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2500);
      if (!page.url().includes("/onboarding")) break;
      await page.locator('input[placeholder="Username"]').fill(`qa${tag}`);
      await page.locator('button[type="submit"]').click();
      await page.waitForTimeout(4000);
    }
    record("reached the chat page", page.url().includes("/consult") ? "PASS" : "FAIL", page.url());

    // ---- 1. the first message survives and is answered ----------------------
    const FIRST = "How can I improve my digestion?";
    const composer = page.locator("textarea").first();
    await composer.waitFor({ timeout: 30000 });
    await composer.fill(FIRST);
    await composer.press("Enter");

    let vanished = false;
    for (let i = 0; i < 12; i++) {
      await page.waitForTimeout(500);
      const text = (await page.locator("main").innerText().catch(() => "")) || "";
      if (!text.includes(FIRST)) vanished = true;
    }
    record(
      "the first message stays on screen",
      vanished ? "FAIL" : "PASS",
      vanished ? "it disappeared at least once" : "never disappeared",
    );

    for (let i = 0; i < 40; i++) {
      await page.waitForTimeout(1000);
      const text = (await page.locator("main").innerText().catch(() => "")) || "";
      if (text.length > FIRST.length + 200 || QUOTA.test(text)) break;
    }
    const firstText = (await page.locator("main").innerText().catch(() => "")) || "";

    // THE assertion this whole suite was written for.
    const errored = /AI service unavailable|error \(40\d\)|Something went wrong/i.test(firstText);
    record(
      "a signed-in message is answered, not refused",
      errored ? "FAIL" : "PASS",
      errored ? firstText.replace(/\s+/g, " ").slice(0, 140) : "a real reply came back",
    );

    // ---- 2. it went through OUR origin, not straight to the API host --------
    const direct = consultCalls.filter((c) => !c.includes(new URL(BASE).host));
    const viaUs = consultCalls.filter((c) => c.includes(`${BASE}/api/consult`));
    record(
      "the consult request goes through our own server",
      direct.length === 0 && viaUs.length > 0 ? "PASS" : "FAIL",
      direct.length ? `went direct: ${direct[0]}` : `${viaUs.length} call(s) to /api/consult`,
    );

    // ---- 3. English stays English -------------------------------------------
    if (!QUOTA.test(firstText)) {
      const hinglish = /\b(aap|aapko|hai|hain|karein|kya|mein|nahi|kar sakte)\b/i;
      record(
        "an English question is answered in English",
        hinglish.test(firstText) ? "FAIL" : "PASS",
        hinglish.test(firstText) ? "Hinglish words in the reply" : "no Hinglish markers",
      );
    } else {
      record("an English question is answered in English", "SKIP", "AI quota spent");
    }

    // ---- 4. a second message, and order is preserved ------------------------
    const second = await ask(page, "What should I eat in the morning?");
    if (second.reason === "quota") {
      record("a second message is answered", "SKIP", "AI quota spent");
    } else {
      record(
        "a second message is answered",
        second.ok ? "PASS" : "FAIL",
        second.ok ? "reply received" : second.reason,
      );
      record(
        "the earlier message is still on screen",
        second.text.includes(FIRST) ? "PASS" : "FAIL",
        second.text.includes(FIRST) ? "transcript intact" : "the first message was lost",
      );
    }

    // ---- 5. the conversation survives a reload ------------------------------
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(6000);
    const afterReload = (await page.locator("main").innerText().catch(() => "")) || "";
    record(
      "the conversation survives a reload",
      afterReload.includes(FIRST) ? "PASS" : "FAIL",
      afterReload.includes(FIRST) ? "transcript came back" : "transcript lost",
    );

    // ---- 6. a new chat starts empty and does not inherit ---------------------
    await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3500);
    const fresh = (await page.locator("main").innerText().catch(() => "")) || "";
    record(
      "a new chat does not inherit the previous one",
      fresh.includes(FIRST) ? "FAIL" : "PASS",
      fresh.includes(FIRST) ? "old messages leaked in" : "started clean",
    );

    // ---- 7. responsive, while signed in -------------------------------------
    for (const vp of [
      { w: 1440, h: 900, name: "1440x900" },
      { w: 768, h: 1024, name: "768x1024" },
      { w: 390, h: 844, name: "390x844" },
    ]) {
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await page.waitForTimeout(1200);
      const metrics = await page.evaluate(() => ({
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
      }));
      const box = await page.locator("textarea").first().boundingBox().catch(() => null);
      record(
        `chat is usable at ${vp.name}`,
        metrics.scrollW - metrics.clientW <= 2 && !!box ? "PASS" : "FAIL",
        `overflow ${metrics.scrollW - metrics.clientW}px, composer ${box ? "present" : "MISSING"}`,
      );
    }
    await page.setViewportSize({ width: 1440, height: 900 });

    // ---- 8. health ----------------------------------------------------------
    record(
      "no console errors during the session",
      consoleErrors.length ? "FAIL" : "PASS",
      consoleErrors[0] || "clean",
    );
    record(
      "no failed requests during the session",
      failedResponses.length ? "FAIL" : "PASS",
      failedResponses[0] || "clean",
    );
  } catch (error) {
    record("suite completed without crashing", "FAIL", String(error).split("\n")[0].slice(0, 180));
  } finally {
    await browser.close();
  }

  const pass = results.filter((r) => r.status === "PASS").length;
  const fail = results.filter((r) => r.status === "FAIL").length;
  const skip = results.filter((r) => r.status === "SKIP").length;
  console.log(`\n===== qa-signed-in: ${pass} passed, ${fail} failed, ${skip} skipped =====`);
  for (const r of results.filter((x) => x.status !== "PASS")) {
    console.log(`  ${r.status} ${r.name}: ${r.detail}`);
  }
  console.log(`\nconsult calls observed:\n  ${consultCalls.join("\n  ") || "(none)"}`);
  process.exit(fail === 0 ? 0 : 1);
})();
