/**
 * End-to-end check of the card-driven consultation.
 *
 * Proves the four things the redesign is judged on:
 *   1. one typed sentence produces tappable question cards
 *   2. the questions are generated per condition, not hardcoded
 *   3. tapping through yields the six-section plan
 *   4. reopening the chat restores a half-finished intake
 *
 * Setup (same as auth-local.js):
 *   1. cd apps/app && next dev -p 3000
 *   2. cd backend-python && python server.py
 *   3. cd packages/backend && npx convex logs > <LOG_FILE>
 *   4. E2E_LOG_FILE=<LOG_FILE> node e2e/consult-local.js
 */
const fs = require("node:fs");
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL || "http://localhost:3000";
const LOG_FILE = process.env.E2E_LOG_FILE;
const ts = Date.now();
// An @example.com address: Resend refuses to deliver to it on the free tier, so
// the backend falls back to logging the code, which is how we read it here.
const EMAIL = `consult${ts}@example.com`;
const PW = "TestUser#2026";
const SLOW = 60000;

const results = [];
let page = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function step(name, fn) {
  try {
    const detail = await fn();
    results.push([true, name, detail || ""]);
    console.log(`PASS  ${name}${detail ? ` - ${detail}` : ""}`);
  } catch (e) {
    const msg = String(e.message).split("\n")[0];
    let ctx = "";
    try {
      ctx = ` [url=${page.url()}]`;
    } catch (_) {}
    results.push([false, name, msg + ctx]);
    console.log(`FAIL  ${name} - ${msg}${ctx}`);
  }
}

async function getCode(email, since = 0) {
  const re = new RegExp(`Code for ${email.replace(/[.+]/g, "\\$&")}:\\s*(\\d{6,8})`, "g");
  for (let i = 0; i < 40; i++) {
    if (LOG_FILE && fs.existsSync(LOG_FILE)) {
      const matches = [...fs.readFileSync(LOG_FILE, "utf8").slice(since).matchAll(re)];
      if (matches.length) return matches[matches.length - 1][1];
    }
    await sleep(1500);
  }
  throw new Error(`no code for ${email}`);
}

const logSize = () => (LOG_FILE && fs.existsSync(LOG_FILE) ? fs.statSync(LOG_FILE).size : 0);
const pwForm = () => page.locator("form.w-72");

/**
 * Never use waitUntil:"networkidle" past the login page — every authenticated
 * screen holds an open Convex WebSocket, so the network is never idle and the
 * navigation hangs until timeout.
 */
async function go(path) {
  await page.goto(BASE + path, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("load").catch(() => {});
  await page.waitForTimeout(1500);
}

/** The intake cards: each is a bordered block holding chips. */
const cards = () => page.locator("div.rounded-2xl", { has: page.locator("button[role=checkbox]") });

async function questionLabels() {
  return (await cards().locator("p.font-semibold").allTextContents()).map((t) => t.trim());
}

(async () => {
  const browser = await chromium.launch({ headless: !process.env.E2E_HEADED });
  const context = await browser.newContext({ viewport: { width: 1366, height: 950 } });
  page = await context.newPage();
  page.setDefaultTimeout(SLOW);

  // ---------------------------------------------------------------- sign in
  const mark = logSize();
  await step("create a verified account to consult with", async () => {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    await page.locator('button[type="button"]:has-text("Create account")').first().click();
    await pwForm().locator('input[type="email"]').fill(EMAIL);
    await pwForm().locator('input[type="password"]').fill(PW);
    await pwForm().locator('button[type="submit"]').click();
    await page.waitForSelector('input[placeholder="Verification code"]', { timeout: SLOW });

    const code = await getCode(EMAIL, mark);
    await pwForm().locator('input[placeholder="Verification code"]').fill(code);
    await pwForm().locator('button[type="submit"]').click();
    await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: SLOW });

    await page.waitForTimeout(2500);
    if (/onboarding/.test(page.url())) {
      await page.fill('input[placeholder="Username"]', `c${String(ts).slice(-8)}`);
      await page.click('button:has-text("Continue")');
      // The redirect is driven by a reactive query, so wait for the URL to move
      // rather than assuming a fixed delay is enough.
      await page
        .waitForURL((u) => !/onboarding/.test(u.toString()), { timeout: SLOW })
        .catch(async () => {
          await go("/");
        });
    }
    if (/onboarding|login/.test(page.url())) {
      throw new Error(`stuck at ${page.url()}`);
    }
    return EMAIL;
  });

  // ------------------------------------------------------------- sidebar
  await step("sidebar shows a single Chat entry, no category list", async () => {
    await go("/consult");
    const nav = await page.locator("aside a").allTextContents();
    const gone = ["General Health", "Diet Plan", "Wellness Plans", "Lifestyle"].filter((c) =>
      nav.some((t) => t.includes(c)),
    );
    if (gone.length) throw new Error(`categories still present: ${gone.join(", ")}`);
    if (!nav.some((t) => t.trim() === "Chat")) throw new Error(`no Chat entry. Got: ${nav.join("|")}`);
    return `${nav.length} nav links, categories removed`;
  });

  // ------------------------------------------------- greeting, no upfront options
  await step("chat opens with a greeting and NO options before the user speaks", async () => {
    await go("/consult");
    const body = await page.textContent("body");
    if (!/Namaste/i.test(body)) throw new Error("no greeting message");

    // Nothing tappable may be offered until the problem is described — options
    // are meant to be chosen for the specific condition.
    const chips = await page.locator("button[role=checkbox]").count();
    const cardCount = await cards().count();
    if (chips > 0 || cardCount > 0) {
      throw new Error(`${chips} chips / ${cardCount} cards shown before typing`);
    }
    return "greeting shown, 0 options";
  });

  // ------------------------------------------------------- conversation router
  // The regression this guards: every message used to be treated as a health
  // complaint, so "hi kaise ho" answered with five symptom cards.
  const smallTalkReplies = [];
  // `assert` is per-case on purpose. The requirement is that the FIRST greeting
  // invites the user to describe their problem — not that every reply ends in a
  // question, which is what made the assistant repeat itself in the first place.
  for (const [message, label, assert] of [
    [
      "hi kaise ho",
      "hinglish greeting",
      (reply) => {
        if (!reply.includes("?")) throw new Error(`first greeting must invite: ${reply}`);
      },
    ],
    [
      "what can you do?",
      "capability question",
      (reply) => {
        if (!/ayurveda|yoga/i.test(reply)) throw new Error(`doesn't say what it does: ${reply}`);
      },
    ],
    [
      "who won the world cup?",
      "off-topic",
      (reply) => {
        // Must decline, not answer. An earlier run had it inventing a result
        // ("world cup ka match toh 2 din pehle hi khela tha") — a health
        // assistant fabricating sports news is worse than being unhelpful.
        if (!/ayurveda|yoga|wellness/i.test(reply)) {
          throw new Error(`did not redirect to its own scope: ${reply}`);
        }
        if (/\b(won|jeet|khela|match|final)\b/i.test(reply)) {
          throw new Error(`answered the off-topic question: ${reply}`);
        }
      },
    ],
  ]) {
    await step(`${label}: replies conversationally, no cards`, async () => {
      await go("/consult");
      await page.fill("textarea", message);
      await page.keyboard.press("Enter");
      // Wait for the loading bubble to go. This used to watch `.animate-bounce`,
      // which stopped existing when the loader was rebuilt - so the selector
      // matched nothing, the wait resolved instantly, and this only LOOKED like
      // it was waiting. The loader is wordless dots now, so there is no visible
      // text to wait on either; the sr-only "Preparing your answer" inside the
      // bubble is the stable handle, because it is an accessibility requirement
      // rather than a styling detail and cannot be quietly dropped.
      await page.waitForFunction(
        () => !document.body.textContent?.includes("Preparing your answer"),
        { timeout: SLOW },
      );
      await page.waitForTimeout(1200);

      if ((await cards().count()) > 0) throw new Error("cards shown for small talk");
      const bubbles = await page.locator("p.whitespace-pre-wrap").allTextContents();
      const reply = (bubbles[bubbles.length - 1] ?? "").trim();
      if (reply.length < 15) throw new Error(`no reply (got "${reply}")`);
      smallTalkReplies.push(reply);
      assert(reply);
      return reply.slice(0, 80);
    });
  }

  await step("replies are generated per message, not one canned string", async () => {
    const unique = new Set(smallTalkReplies.map((r) => r.trim()));
    if (unique.size < smallTalkReplies.length) {
      throw new Error("the same reply came back for different messages");
    }
    return `${unique.size} distinct replies`;
  });

  await step("a general question is answered directly, still without cards", async () => {
    await go("/consult");
    await page.fill("textarea", "what is ashwagandha?");
    await page.keyboard.press("Enter");
    // Same stable handle as above - see the note there.
    await page.waitForFunction(
      () => !document.body.textContent?.includes("Preparing your answer"),
      { timeout: SLOW },
    );
    await page.waitForTimeout(1200);
    if ((await cards().count()) > 0) throw new Error("cards shown for a general question");
    const bubbles = await page.locator("p.whitespace-pre-wrap").allTextContents();
    const reply = (bubbles[bubbles.length - 1] ?? "").trim();
    if (reply.length < 80) throw new Error(`answer too short: ${reply}`);
    return `${reply.length} chars`;
  });

  // --------------------------------------------------- one sentence -> cards
  let acidityLabels = [];
  await step("typing one sentence returns tappable question cards", async () => {
    await go("/consult");
    await page.fill("textarea", "I have acidity and burning after meals");
    await page.keyboard.press("Enter");
    await cards().first().waitFor({ state: "visible", timeout: SLOW });
    await page.waitForTimeout(1200);

    const count = await cards().count();
    const chips = await page.locator("button[role=checkbox]").count();
    acidityLabels = await questionLabels();
    // How many questions the planner asks for is the model's call (the prompt
    // asks for 4-6, the repair layer caps at 6). Assert it produced a usable
    // tappable form, not an exact count that varies with the model in use.
    if (count < 2) throw new Error(`only ${count} cards`);
    if (chips < 6) throw new Error(`only ${chips} chips`);
    return `${count} cards, ${chips} tappable options`;
  });

  await step("a progress indicator is shown above the cards", async () => {
    // Scoped to the intake header, so an unrelated "1/2" elsewhere can't pass this.
    const counter = page.locator("span.tabular-nums").first();
    await counter.waitFor({ state: "visible", timeout: 15000 });
    const value = ((await counter.textContent()) ?? "").trim();
    if (!/^\d+\/\d+$/.test(value)) throw new Error(`counter read "${value}"`);
    return value;
  });

  // ------------------------------------- tapping -> "what do you want?" step
  await step("after answering, it asks what the user wants in the plan", async () => {
    // Tap the first SAFE chip of each card, as a user without an emergency
    // would. Skipping `data-red-flag` matters: the planner marks options like
    // "chest pain" or "blood in stool", selecting one correctly ends the
    // consultation with a referral, and this step would then wait forever for a
    // delivery question that is never going to come. The old code took chip [0]
    // blindly and passed only by luck.
    const count = await cards().count();
    for (let i = 0; i < count; i++) {
      const chip = cards()
        .nth(i)
        .locator('button[role=checkbox]:not([data-red-flag="true"])')
        .first();
      if (await chip.count()) await chip.click();
    }
    await page.locator('button:has-text("Get my plan"), button:has-text("Continue")').first().click();

    // The delivery step, not the plan itself.
    await page.waitForSelector("text=/What would you like in your plan/i", { timeout: 120000 });
    await page.waitForTimeout(1200);

    const chipLabels = await page.locator("button[role=checkbox]").allTextContents();
    const expected = ["Complete plan", "Root cause", "Food chart", "Yoga"];
    const missing = expected.filter((e) => !chipLabels.some((c) => c.includes(e)));
    if (missing.length) throw new Error(`missing options: ${missing.join(", ")}`);
    // The "anything else?" free-text box must be offered too.
    if ((await page.locator('textarea[placeholder*="Type here"]').count()) === 0) {
      throw new Error("no 'anything else' text field");
    }
    return `${chipLabels.length} choices offered`;
  });

  await step("choosing only Food chart returns just that section", async () => {
    await page
      .locator('button[role=checkbox]:has-text("Food chart")')
      .first()
      .click();
    await page.locator('button:has-text("Get my plan"), button:has-text("Continue")').first().click();

    // Wait for the rendered PLAN, not for the text "Food Chart" — that phrase is
    // already on screen as a choice chip, so a text wait returns instantly and
    // the assertions then run against a page with no plan on it yet.
    await page.waitForFunction(
      () => document.querySelectorAll("div.rounded-xl > div.font-semibold").length > 0,
      { timeout: 180000 },
    );
    await page.waitForTimeout(1500);

    // Read the rendered plan only — the choice chips above still say "Root cause"
    // etc., so scanning the whole page would always "find" every section.
    const headings = await page
      .locator("div.rounded-xl > div.font-semibold")
      .allTextContents();
    const titles = headings.map((h) => h.trim());
    const hasFood = titles.some((t) => /food chart/i.test(t));
    const leaked = titles.filter((t) => /root cause|daily routine|changes to make/i.test(t));
    if (!hasFood) throw new Error(`no Food Chart section. Got: ${titles.join(" | ")}`);
    if (leaked.length) throw new Error(`unrequested sections present: ${leaked.join(", ")}`);
    return `sections rendered: ${titles.join(" | ")}`;
  });

  // ------------------------------------------- different condition, different form
  await step("a different condition generates different questions", async () => {
    await go("/consult");
    await page.fill("textarea", "I get migraine headaches twice a week");
    await page.keyboard.press("Enter");
    await cards().first().waitFor({ state: "visible", timeout: SLOW });
    await page.waitForTimeout(1200);

    const migraineLabels = await questionLabels();
    const shared = migraineLabels.filter((l) => acidityLabels.includes(l));
    if (migraineLabels.length === 0) throw new Error("no questions generated");
    if (shared.length > 1) {
      throw new Error(`${shared.length} identical questions - looks hardcoded`);
    }
    return `acidity ${acidityLabels.length}q vs migraine ${migraineLabels.length}q, ${shared.length} shared`;
  });

  // ------------------------------------------------------------- resume
  await step("reopening the chat restores the half-finished intake", async () => {
    const chatUrl = page.url();
    if (!/[?&]c=/.test(chatUrl)) throw new Error(`session id not in URL: ${chatUrl}`);

    // Tap one option, then reload as if the user came back later.
    await cards().first().locator("button[role=checkbox]").first().click();
    await page.waitForTimeout(2500);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);

    const restored = await cards().count();
    if (restored === 0) throw new Error("cards did not come back after reload");
    return `${restored} cards restored from saved state`;
  });

  await browser.close();

  const passed = results.filter((r) => r[0]).length;
  console.log(`\n========= CONSULT E2E: ${passed}/${results.length} =========`);
  for (const [ok, name, detail] of results) {
    console.log(`${ok ? "✓" : "✗"} ${name}${detail ? ` - ${detail}` : ""}`);
  }
  process.exit(passed === results.length ? 0 : 1);
})().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});
