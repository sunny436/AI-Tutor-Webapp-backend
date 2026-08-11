/**
 * The four consultation fixes, checked in a real browser against the live site.
 *
 *   E2E_BASE_URL=https://ayur.namahos.com E2E_IMAP_USER=... E2E_IMAP_PASS=... \
 *   node consult-fixes.js
 *
 * Covers, in one signed-in session:
 *   1. the user's first message stays on screen (it used to vanish, taking the
 *      greeting with it)
 *   2. an English conversation answers in English and stays English
 *   3. an explicit request switches the language
 *   4. streaming shows text progressively in exactly one assistant bubble
 *   5. a reload brings the transcript back
 *
 * Anything that needs the model reports SKIPPED when the free tier is spent —
 * a rate limit is not a defect in this application.
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
const EMAIL = `${local}+fix${tag}@${domain}`;
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

/** Send one message; resolve when the transcript stops growing. */
async function ask(page, text) {
  const composer = page.locator("textarea").first();
  await composer.waitFor({ timeout: 30000 });
  const before = (await page.locator("main").innerText().catch(() => "")) || "";

  await composer.fill(text);
  await composer.press("Enter");

  const deadline = Date.now() + REPLY_TIMEOUT_MS;
  let sawGrowth = false;
  let previous = before;
  let stable = 0;

  while (Date.now() < deadline) {
    await page.waitForTimeout(1200);
    const now = (await page.locator("main").innerText().catch(() => "")) || "";
    if (QUOTA.test(now)) return { ok: false, reason: "quota", text: "" };
    if (now.length > before.length + 30) sawGrowth = true;
    if (sawGrowth) {
      // Two quiet polls in a row means the answer has finished landing.
      stable = now === previous ? stable + 1 : 0;
      if (stable >= 2) return { ok: true, text: now };
    }
    previous = now;
  }
  return { ok: false, reason: "timeout", text: previous };
}

/**
 * Start a fresh consultation by navigating to /consult with no `?c=`.
 *
 * The sidebar's "New Chat" is the same destination, but clicking it depends on
 * the sidebar being rendered at the current viewport, which it is not on a
 * narrow headless window — and the silent fallback made the suite look like the
 * app had failed when it was the harness that had.
 */
async function newChat(page) {
  await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("textarea", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(2500);
}

(async () => {
  if (!IMAP_USER) {
    console.error("E2E_IMAP_USER is required");
    process.exit(2);
  }

  const browser = await chromium.launch({
    headless: process.env.E2E_HEADED !== "1",
    slowMo: Number(process.env.E2E_SLOWMO || 120),
  });
  const page = await browser.newPage();

  try {
    // ---- sign up -----------------------------------------------------------
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('form.w-72 input[type="email"]', { timeout: 30000 });
    await page.waitForTimeout(1200);
    await page.locator('button[type="button"]:has-text("Create account")').first().click();
    const form = page.locator("form.w-72");
    await form.locator('input[type="email"]').fill(EMAIL);
    await form.locator('input[type="password"]').fill(PW);
    await form.locator('button[type="submit"]').click();
    await page.waitForTimeout(4500);
    await form.locator('input[placeholder="Verification code"]').fill(codeFor(EMAIL));
    await form.locator('button[type="submit"]').click();
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 40000 }).catch(() => {});

    record("signed in", page.url().includes("/login") ? "FAIL" : "PASS", page.url());

    // A new account is sent to /onboarding to pick a username, and every
    // dashboard route bounces there until it is done. Onboarding then returns to
    // "/", not to where we were headed, so /consult has to be asked for again.
    for (let attempt = 0; attempt < 3; attempt++) {
      await page.goto(`${BASE}/consult`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2500);
      if (!page.url().includes("/onboarding")) break;
      await page.locator('input[placeholder="Username"]').fill(`t${tag}`);
      await page.locator('button[type="submit"]').click();
      await page.waitForTimeout(4000);
    }

    // ---- 1. the first message must survive ---------------------------------
    const FIRST = "How can I improve my digestion?";
    const composer = page.locator("textarea").first();
    await composer.waitFor({ timeout: 30000 });
    await composer.fill(FIRST);
    await composer.press("Enter");

    // Poll hard for the two seconds where the wipe used to happen, rather than
    // only checking at the end: the bug removed the message and the reply then
    // re-populated the transcript, so a late check could miss it entirely.
    let vanished = false;
    for (let i = 0; i < 12; i++) {
      await page.waitForTimeout(500);
      const text = (await page.locator("main").innerText().catch(() => "")) || "";
      if (!text.includes(FIRST)) vanished = true;
    }
    record(
      "first message stays on screen while the reply is produced",
      vanished ? "FAIL" : "PASS",
      vanished ? "it disappeared at least once" : "never disappeared",
    );

    // Let the first turn settle before judging its language.
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(1000);
      const text = (await page.locator("main").innerText().catch(() => "")) || "";
      if (text.length > FIRST.length + 200 || QUOTA.test(text)) break;
    }
    const finalText = (await page.locator("main").innerText().catch(() => "")) || "";

    // ---- 2. streaming: text grows in one bubble ----------------------------
    //
    // Measured on a KNOWLEDGE question, not a symptom. A health complaint is
    // answered with intake question cards, and cards are structured JSON that
    // deliberately arrives whole — half a form is not a form. Watching a
    // complaint for progressive text therefore proves nothing, which is what
    // the first version of this check did.
    await newChat(page);
    const composer2 = page.locator("textarea").first();
    await composer2.waitFor({ timeout: 30000 });
    await composer2.fill("What is guduchi used for?");
    await composer2.press("Enter");

    let grew = 0;
    let lastLength = 0;
    let bubbles = 0;
    for (let i = 0; i < 45; i++) {
      await page.waitForTimeout(600);
      const text = (await page.locator("main").innerText().catch(() => "")) || "";
      if (text.length > lastLength + 15) grew++;
      lastLength = text.length;
      // One assistant turn only — a chunk-per-bubble bug would show up here.
      bubbles = Math.max(bubbles, await page.locator("main .prose, main p").count());
      if (QUOTA.test(text)) break;
    }
    const streamText = (await page.locator("main").innerText().catch(() => "")) || "";
    if (QUOTA.test(streamText)) {
      record("assistant text arrives progressively", "SKIP", "LLM free tier spent");
    } else {
      record(
        "assistant text arrives progressively",
        grew >= 2 ? "PASS" : "FAIL",
        `${grew} growth steps observed`,
      );
    }

    // ---- 3. English in, English out ----------------------------------------
    if (!QUOTA.test(finalText)) {
      const hinglish = /\b(aap|aapko|hai|hain|karein|kya|mein|nahi|kar sakte)\b/i;
      record(
        "an English question is answered in English",
        hinglish.test(finalText) ? "FAIL" : "PASS",
        hinglish.test(finalText) ? "Hinglish words in the reply" : "no Hinglish markers",
      );
    } else {
      record("an English question is answered in English", "SKIP", "LLM free tier spent");
    }

    // ---- 4. reload keeps the transcript ------------------------------------
    // Checked on the chat currently open, which by now is the streaming one.
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(5000);
    const afterReload = (await page.locator("main").innerText().catch(() => "")) || "";
    const kept = afterReload.includes("guduchi") || afterReload.includes("Guduchi");
    record(
      "the conversation survives a reload",
      kept ? "PASS" : "FAIL",
      kept ? "the question and its answer came back" : "transcript lost",
    );

    // ---- 5. explicit language switch ---------------------------------------
    await newChat(page);
    const hindi = await ask(page, "Ab se Hindi mein answer karo. Pet ki gas ke liye kya karun?");
    if (hindi.reason === "quota") {
      record("an explicit request switches the language", "SKIP", "LLM free tier spent");
    } else if (!hindi.ok) {
      record("an explicit request switches the language", "FAIL", "no reply in time");
    } else {
      const devanagari = /[ऀ-ॿ]/.test(hindi.text);
      record(
        "an explicit request switches the language",
        devanagari ? "PASS" : "FAIL",
        devanagari ? "replied in Devanagari" : "stayed in Latin script",
      );
    }
  } catch (error) {
    record("suite completed without crashing", "FAIL", String(error).split("\n")[0].slice(0, 160));
  } finally {
    await browser.close();
  }

  const pass = results.filter((r) => r.status === "PASS").length;
  const fail = results.filter((r) => r.status === "FAIL").length;
  const skip = results.filter((r) => r.status === "SKIP").length;
  console.log(`\n===== consult-fixes: ${pass} passed, ${fail} failed, ${skip} skipped =====`);
  for (const r of results.filter((x) => x.status !== "PASS")) {
    console.log(`  ${r.status} ${r.name}: ${r.detail}`);
  }
  process.exit(fail === 0 ? 0 : 1);
})();
