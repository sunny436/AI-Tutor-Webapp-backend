/**
 * Accessibility and responsive checks for the pages a signed-out visitor sees.
 *
 *   node e2e/p7-a11y.js            (NODE, never bun — see README)
 *
 * Targets BASE (default http://127.0.0.1:3100), which is expected to be a
 * throwaway server, not production. Start one with an isolated build dir so it
 * cannot touch the `.next` a running `next start` is serving:
 *
 *   cd apps/app && NEXT_DIST_DIR=.next-dev-verify bun run dev -- -p 3100
 *
 * WHAT THIS EXISTS TO CATCH
 * Three WCAG Level A failures found by measuring rather than eyeballing:
 *   1. no skip link anywhere, while the dashboard renders 14 nav links before
 *      <main> — every page, every keyboard user (2.4.1 Bypass Blocks);
 *   2. no <main> landmark at all on the landing, login and onboarding pages —
 *      the three a new user meets first;
 *   3. <html lang> hardcoded to "en" regardless of route (3.1.1).
 *
 * Plus the seven widths from the brief, checking the one thing that actually
 * breaks on a phone: horizontal overflow.
 */

const { chromium } = require("playwright");

const BASE = process.env.BASE || "http://127.0.0.1:3100";

// From the brief. 375 is the narrowest phone still worth supporting; 430 is a
// modern large phone; 768 is the tablet breakpoint where the sidebar changes.
const WIDTHS = [1440, 1280, 1024, 768, 430, 390, 375];

const PAGES = [
  { path: "/en", name: "landing" },
  { path: "/en/login", name: "login" },
  { path: "/en/library", name: "library index" },
  { path: "/en/library/acidity", name: "library note" },
];

const results = [];
const check = (name, ok, detail = "") => {
  results.push([name, ok, detail]);
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
};

(async () => {
  const browser = await chromium.launch();

  // --- 1. landmarks and the skip link ---------------------------------------
  console.log("\nlandmarks + skip link");
  {
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();

    for (const { path, name } of PAGES) {
      await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });

      const mains = await page.locator("main").count();
      check(`${name}: has exactly one <main>`, mains === 1, `${mains} found`);

      const target = await page.locator("main#main").count();
      check(`${name}: <main> carries id="main" for the skip link`, target === 1);

      // The skip link must be the FIRST thing a keyboard reaches, or it cannot
      // do its job.
      await page.keyboard.press("Tab");
      const focused = await page.evaluate(() => {
        const el = document.activeElement;
        return el ? { text: (el.textContent || "").trim(), href: el.getAttribute("href") } : null;
      });
      check(
        `${name}: first Tab reaches the skip link`,
        focused?.href === "#main",
        `focused: ${focused?.text || "nothing"}`,
      );

      // Visually hidden until focused, then genuinely visible — a skip link that
      // stays invisible while focused is worse than none at all.
      const visible = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el) return null;
        const box = el.getBoundingClientRect();
        return { w: Math.round(box.width), h: Math.round(box.height) };
      });
      check(
        `${name}: the focused skip link is actually visible`,
        (visible?.w ?? 0) > 40 && (visible?.h ?? 0) > 20,
        `${visible?.w}x${visible?.h}`,
      );
    }

    // --- 2. lang -------------------------------------------------------------
    console.log("\nhtml lang follows the route");
    await page.goto(`${BASE}/en`, { waitUntil: "domcontentloaded" });
    check("/en -> lang='en'", (await page.getAttribute("html", "lang")) === "en");

    await page.goto(`${BASE}/fr`, { waitUntil: "domcontentloaded" });
    const fr = await page.getAttribute("html", "lang");
    check("/fr -> lang='fr', not the hardcoded 'en'", fr === "fr", String(fr));

    // The Library body is romanised Hindi. Claiming English makes a screen
    // reader pronounce it with English phonetics, which is gibberish.
    await page.goto(`${BASE}/en/library/acidity`, { waitUntil: "domcontentloaded" });
    const hinglish = await page.locator("[lang='hi-Latn']").count();
    check("library note tags its Hinglish body as hi-Latn", hinglish > 0, `${hinglish} elements`);

    // --- 3. the safety section is not buried ---------------------------------
    const doctorY = await page
      .locator("#see-a-doctor")
      .evaluate((el) => el.getBoundingClientRect().top + window.scrollY)
      .catch(() => -1);
    check("library note pins 'When to see a doctor' near the top", doctorY > 0 && doctorY < 900, `y=${Math.round(doctorY)}`);

    await page.close();
  }

  // --- 4. seven widths, no horizontal overflow -------------------------------
  console.log("\nresponsive: no horizontal scroll at any width");
  for (const width of WIDTHS) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();

    for (const { path, name } of PAGES) {
      await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
      const overflow = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      // 1px of slack: sub-pixel layout rounding is not a horizontal scrollbar.
      check(
        `${width}px ${name}: body does not scroll sideways`,
        overflow.scroll <= overflow.client + 1,
        `${overflow.scroll} > ${overflow.client}`,
      );
    }
    await context.close();
  }

  await browser.close();

  const passed = results.filter(([, ok]) => ok).length;
  console.log(`\n===== p7 a11y+responsive: ${passed}/${results.length} passed =====`);
  if (passed !== results.length) {
    console.log("\nFailing:");
    for (const [name, ok, detail] of results) if (!ok) console.log(`  - ${name}: ${detail}`);
  }
  process.exit(passed === results.length ? 0 : 1);
})().catch((error) => {
  console.error("p7-a11y crashed:", error);
  process.exit(1);
});
