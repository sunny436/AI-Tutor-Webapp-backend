/**
 * Live browser walkthrough of the chat, with screenshots.
 *
 * Not a replacement for consult-local.js — that one asserts. This one DRIVES the
 * real UI the way a user does and captures what the screen actually looked like,
 * so the answer text, the cards and the section colouring can be judged by eye
 * rather than by a passing assertion.
 *
 * Setup (same as the other suites):
 *   1. backend-python: python server.py            (:4000)
 *   2. apps/app:       next dev -p 3000            (:3000)
 *   3. packages/backend: npx convex logs > <file>  (for the sign-up code)
 *   4. E2E_LOG_FILE=<file> node e2e/live-check.js
 *
 * Env: E2E_BASE_URL, E2E_LOG_FILE, E2E_SHOTS, E2E_HEADED=1
 */
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL || "http://localhost:3000";
const LOG_FILE = process.env.E2E_LOG_FILE;
const SHOTS = process.env.E2E_SHOTS || path.join(__dirname, "shots");
const EMAIL = `live${Date.now()}@example.com`;
const PW = "LiveTest#2026";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let step = 0;

fs.mkdirSync(SHOTS, { recursive: true });

async function shot(page, name) {
  const file = path.join(SHOTS, `${String(++step).padStart(2, "0")}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`   shot -> ${file}`);
}

async function getCode(email) {
  if (!LOG_FILE) throw new Error("E2E_LOG_FILE not set");
  const re = new RegExp(`Code for ${email.replace(/[.+]/g, "\\$&")}:\\s*(\\d{6,8})`, "g");
  for (let i = 0; i < 40; i++) {
    if (fs.existsSync(LOG_FILE)) {
      const matches = [...fs.readFileSync(LOG_FILE, "utf8").matchAll(re)];
      if (matches.length) return matches[matches.length - 1][1];
    }
    await sleep(1500);
  }
  throw new Error(`no verification code for ${email}`);
}

/** The newest assistant bubble's text. */
async function lastReply(page) {
  const bubbles = page.locator("div.rounded-2xl, div.rounded-xl").filter({ hasText: /\S/ });
  const count = await bubbles.count();
  return count ? ((await bubbles.nth(count - 1).innerText()) || "").trim() : "";
}

async function send(page, text, { wait = 60000 } = {}) {
  const before = await lastReply(page);
  const box = page.locator('textarea, input[type="text"]').last();
  await box.fill(text);
  await box.press("Enter");
  // Wait for the reply to actually change rather than a fixed sleep.
  const deadline = Date.now() + wait;
  while (Date.now() < deadline) {
    await sleep(1200);
    const now = await lastReply(page);
    if (now && now !== before && now.length > 5) return now;
  }
  return await lastReply(page);
}

(async () => {
  const browser = await chromium.launch({ headless: !process.env.E2E_HEADED });
  const page = await browser.newContext({ viewport: { width: 1280, height: 900 } }).then((c) => c.newPage());
  page.setDefaultTimeout(45000);
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  // ---------------------------------------------------------------- sign up
  console.log("1. sign up and verify");
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.locator('button[type="button"]:has-text("Create account")').first().click();
  const form = page.locator("form.w-72");
  await form.locator('input[type="email"]').fill(EMAIL);
  await form.locator('input[type="password"]').fill(PW);
  await form.locator('button[type="submit"]').click();
  await page.waitForSelector('input[placeholder="Verification code"]', { timeout: 40000 });
  await form.locator('input[placeholder="Verification code"]').fill(await getCode(EMAIL));
  await form.locator('button[type="submit"]').click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 60000 });

  console.log("2. open the chat");
  await page.goto(`${BASE}/consult`, { waitUntil: "networkidle" });
  await sleep(4000);
  await shot(page, "greeting");
  console.log(`   greeting: ${(await lastReply(page)).slice(0, 100)}`);

  // ------------------------------------------------- Hinglish general question
  console.log("3. Hinglish question -> expect a Hinglish answer, no cards");
  let reply = await send(page, "acidity ke liye kya khana chahiye");
  console.log(`   ${reply.slice(0, 160).replace(/\n/g, " ")}`);
  await shot(page, "hinglish-answer");

  // ----------------------------------------------------- follow-up: translate
  console.log("4. follow-up 'explain this in english' -> same content, English");
  reply = await send(page, "explain this in english");
  console.log(`   ${reply.slice(0, 160).replace(/\n/g, " ")}`);
  await shot(page, "translated");

  // ------------------------------------------------------------- Devanagari
  console.log("5. Devanagari question -> expect a Devanagari answer");
  await page.goto(`${BASE}/consult`, { waitUntil: "networkidle" });
  await sleep(3500);
  reply = await send(page, "बवासीर के लिए क्या करें");
  console.log(`   ${reply.slice(0, 160).replace(/\n/g, " ")}`);
  await shot(page, "devanagari-answer");

  // --------------------------------------------------- complaint -> the cards
  console.log("6. a real complaint -> question cards");
  await page.goto(`${BASE}/consult`, { waitUntil: "networkidle" });
  await sleep(3500);
  await send(page, "mujhe bahut acidity ho rahi hai", { wait: 75000 });
  await sleep(2500);
  const cards = page.locator("div.rounded-xl > div.font-semibold");
  console.log(`   ${await cards.count()} question cards`);
  await shot(page, "intake-cards");

  // Answer every card by tapping its first SAFE option. Red-flag chips are
  // skipped via the data attribute rather than by matching text, because the
  // labels are model-written and now come back in Hinglish and Devanagari too.
  for (const group of await page.locator("div.rounded-xl").all()) {
    const chip = group
      .locator('button[role=checkbox]:not([data-red-flag="true"])')
      .first();
    if (await chip.count()) await chip.click().catch(() => {});
  }
  await shot(page, "cards-answered");

  const cont = page.locator('button:has-text("Continue"), button:has-text("Aage")').first();
  if (await cont.count()) {
    await cont.click();
    await sleep(9000);
    await shot(page, "delivery-choices");
    const complete = page.locator("button", { hasText: /complete|poora|sab/i }).first();
    if (await complete.count()) await complete.click().catch(() => {});
    const go = page.locator('button:has-text("Continue"), button:has-text("Aage")').first();
    if (await go.count()) {
      await go.click();
      await sleep(30000);
    }
  }
  const plan = await lastReply(page);
  const headings = [...plan.matchAll(/^(Root Cause|Changes To Make|Food Chart|Daily Routine|Yoga & Breathing|When To See A Doctor)\s*$/gim)];
  console.log(`   plan ${plan.length} chars, ${headings.length}/6 headings rendered`);
  await shot(page, "final-plan");

  console.log(`\nconsole errors: ${errors.length}`);
  errors.slice(0, 5).forEach((e) => console.log(`   - ${e.slice(0, 120)}`));
  console.log(`screenshots in ${SHOTS}`);
  await browser.close();
})().catch(async (error) => {
  console.error("LIVE CHECK FAILED:", error.message);
  process.exit(1);
});
