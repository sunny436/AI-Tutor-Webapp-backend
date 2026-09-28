import type { Page } from "@playwright/test";

import {
  chatLinks,
  composer,
  emptyGreeting,
  expect,
  expectAccessible,
  expectNoHorizontalOverflow,
  expectStudyGreeting,
  lastReply,
  renameChat,
  seedTurn,
  send,
  sendAndWait,
  test,
  waitForHydration,
  waitForIdle,
} from "./support";

/**
 * The chat's polish, as a student sees it: the header is the chat's name and chats are named
 * after their first answered question; the composer has no placeholder or footer; three dots
 * and nothing else until the first words; replies stream evenly and never show half-typed
 * Markdown, and do it within budget; the new chat's greeting; long titles in the sidebar.
 */

const heading = (page: Page) => page.getByRole("banner").getByRole("heading", { level: 1 });

/** "Ask New Doubt", and wait until the new chat is on screen (typing sooner would go to the old one). */
async function newChat(page: Page): Promise<void> {
  await page.getByRole("link", { name: "Ask New Doubt" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(heading(page)).toHaveText("New chat");
  await expectStudyGreeting(page);
}

test("the header is the chat's name: New chat, then named after the first answered question", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  await expect(heading(page)).toHaveText("New chat");
  await expect(page).toHaveTitle(/^New chat · /);
  // The chat is not listed as a tool of its own, and no slogan repeats it.
  await expect(page.getByText(/AI Tutor|Personal Doubts Solver/)).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Learning Hub" })).toHaveCount(0);

  await send(page, "Hi");
  await waitForIdle(page);
  await expect(heading(page)).toHaveText("New chat"); // small talk names nothing

  await sendAndWait(page, "Can you explain photosynthesis?");
  await expect(heading(page)).toHaveText("Photosynthesis Explained");
  await expect(chatLinks(page)).toHaveText(["Photosynthesis Explained"]);
  await expect(page).toHaveTitle(/^Photosynthesis Explained · /);

  await sendAndWait(page, "What is the difference between mitosis and meiosis?");
  await expect(heading(page)).toHaveText("Photosynthesis Explained"); // named once
  await page.reload();
  await expect(heading(page)).toHaveText("Photosynthesis Explained");
  await expect(chatLinks(page)).toHaveText(["Photosynthesis Explained"]);
});

test("the composer: no placeholder, no lines under it; its name and keys are for assistive technology", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  const box = composer(page);
  await expect(box).toHaveAccessibleName("Ask your doubt");
  await expect(box).toHaveAccessibleDescription("Enter to send, Shift + Enter for a new line.");
  expect(await box.getAttribute("placeholder")).toBeNull();
  await expect(page.getByText(/Powered by|can make mistakes/)).toHaveCount(0);
  await expect(page.getByText("Enter to send, Shift + Enter for a new line.")).toHaveClass(/sr-only/);
  // Near the limit the count shows, in the same place.
  await box.fill("x".repeat(15_100));
  await expect(page.getByText("15,100 / 16,000")).toBeVisible();
  await box.fill("");
  await expect(page.getByText(/\/ 16,000/)).toHaveCount(0);
});

/** Records, in the page, what a streaming reply looks like at every change. */
async function watchReplies(page: Page): Promise<void> {
  await page.evaluate(() => {
    type Watch = {
      dotsAt: number | null;
      dotsGoneAt: number | null;
      firstTextAt: number | null;
      generatingText: boolean;
      katexErrors: number;
      rawMarkers: string[];
      firstBlock: Element | null;
      firstBlockReplaced: boolean;
      commits: number[];
      samples: { t: number; length: number }[];
      settledLength: number | null;
      longTasks: number[];
    };
    const watch: Watch = {
      dotsAt: null,
      dotsGoneAt: null,
      firstTextAt: null,
      generatingText: false,
      katexErrors: 0,
      rawMarkers: [],
      firstBlock: null,
      firstBlockReplaced: false,
      commits: [],
      samples: [],
      settledLength: null,
      longTasks: [],
    };
    Object.assign(window, { __watch: watch });
    const reply = () => [...document.querySelectorAll('article[aria-label="Assistant"]')].at(-1) ?? null;
    const content = () => reply()?.querySelector(".message-content") ?? null;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) watch.longTasks.push(entry.duration);
    }).observe({ entryTypes: ["longtask"] });
    new MutationObserver((records) => {
      const now = performance.now();
      const article = reply();
      if (!article) return;
      // A change inside the reply is one of its commits (its insertion is a change to the list).
      if (records.some((record) => article.contains(record.target))) watch.commits.push(now);
      const dots = article.querySelector("[data-streaming-dots]");
      if (dots && watch.dotsAt === null) watch.dotsAt = now;
      if (!dots && watch.dotsAt !== null && watch.dotsGoneAt === null) watch.dotsGoneAt = now;
      if (/generating/i.test(article.textContent ?? "")) watch.generatingText = true;
      const box = content();
      if (!box) return;
      if ((box.textContent ?? "").length > 0 && watch.firstTextAt === null) watch.firstTextAt = now;
      if (box.querySelector(".katex-error")) watch.katexErrors += 1;
      const visible = (box.textContent ?? "").replace(/```[\s\S]*?```/g, "");
      if (/\*\*|\$/.test(visible)) watch.rawMarkers.push(visible.slice(-60));
      if (box.children.length > 1 && watch.firstBlock === null) watch.firstBlock = box.firstElementChild;
      if (watch.firstBlock && (box.firstElementChild !== watch.firstBlock || !watch.firstBlock.isConnected)) {
        watch.firstBlockReplaced = true;
      }
      if (article.getAttribute("aria-busy") === "false" && watch.settledLength === null) {
        watch.settledLength = (box.textContent ?? "").length;
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["aria-busy"] });
    setInterval(() => {
      const box = content();
      if (box && reply()?.getAttribute("aria-busy") === "true") {
        watch.samples.push({ t: performance.now(), length: (box.textContent ?? "").length });
      }
    }, 50);
  });
}

type Watch = {
  dotsAt: number | null;
  dotsGoneAt: number | null;
  firstTextAt: number | null;
  generatingText: boolean;
  katexErrors: number;
  rawMarkers: string[];
  firstBlockReplaced: boolean;
  commits: number[];
  samples: { t: number; length: number }[];
  settledLength: number | null;
  longTasks: number[];
};
const watched = (page: Page) =>
  page.evaluate(() => {
    const { firstBlock: _, ...rest } = (window as unknown as { __watch: Watch & { firstBlock: unknown } }).__watch;
    return rest as Watch;
  });

test("three dots and nothing else until the first words, then the words replace them", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  await watchReplies(page);
  await sendAndWait(page, "Explain photosynthesis");
  const watch = await watched(page);
  expect(watch.dotsAt, "the dots showed").not.toBeNull();
  expect(watch.firstTextAt, "then the words").not.toBeNull();
  expect(watch.dotsAt as number).toBeLessThanOrEqual(watch.firstTextAt as number);
  expect((watch.dotsGoneAt as number) - (watch.firstTextAt as number), "gone with the first words").toBeLessThanOrEqual(100);
  expect(watch.generatingText, "no 'generating' text").toBe(false);
  await expect(lastReply(page).locator("[data-streaming-dots]")).toHaveCount(0);
});

/** A tutor-like reply of about 2,000 characters: headings, lists, bold, code, maths, a table. */
const RICH = [
  "Here is the whole picture.",
  "",
  "# Photosynthesis",
  "",
  "Plants turn **light energy** into chemical energy. The overall equation is $6CO_2 + 6H_2O \\to C_6H_{12}O_6 + 6O_2$ and it happens in the `chloroplast`.",
  "",
  "## The two stages",
  "",
  "1. **Light reactions** split water and make ATP and NADPH.",
  "2. **The Calvin cycle** fixes carbon dioxide into sugar.",
  "",
  "$$",
  "\\text{rate} = \\frac{\\Delta O_2}{\\Delta t}",
  "$$",
  "",
  "| Stage | Where | Makes |",
  "|---|---|---|",
  "| Light reactions | Thylakoid | ATP, NADPH, O2 |",
  "| Calvin cycle | Stroma | Glucose |",
  "",
  "```python",
  "def rate(oxygen, seconds):",
  "    return oxygen / seconds",
  "```",
  "",
  "- Chlorophyll absorbs red and blue light, so leaves look green.",
  "- More light raises the rate until another factor limits it.",
  "- Temperature matters because the enzymes of the Calvin cycle work best when warm.",
  "",
  "## Why it matters",
  "",
  "Almost every food chain starts with photosynthesis, and it keeps the oxygen in the air we breathe. ".repeat(6).trim(),
  "",
  "**Summary:** light in, sugar and oxygen out.",
].join("\n");

test("a long rich reply streams evenly, never half-typed, within budget, and ends as it reloads", async ({
  page,
  account: _,
}) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await waitForHydration(page);
  await watchReplies(page);
  const started = Date.now();
  await sendAndWait(page, RICH);
  const seconds = (Date.now() - started) / 1000;
  const watch = await watched(page);

  // Never a maths error or a raw ** / $$ on screen, and finished blocks are never redrawn.
  expect(watch.katexErrors, "katex errors while streaming").toBe(0);
  expect(watch.rawMarkers, "raw Markdown markers while streaming").toEqual([]);
  expect(watch.firstBlockReplaced, "the first block was redrawn").toBe(false);

  // Even: most steps are small; everything is on screen the moment it completes.
  const steps = watch.samples.slice(1).map((sample, index) => sample.length - (watch.samples[index]?.length ?? 0));
  const moving = steps.filter((step) => step > 0);
  expect(moving.length, "it moved many times").toBeGreaterThan(20);
  expect(moving.filter((step) => step <= 120).length / moving.length).toBeGreaterThanOrEqual(0.8);
  const final = await lastReply(page).locator(".message-content").evaluate((element) => (element.textContent ?? "").length);
  expect(watch.settledLength, "all of it when it finished").toBe(final);

  // Budget: no long task over 150 ms; long tasks under 15% of the streaming time; <= 25 commits/s.
  expect(Math.max(0, ...watch.longTasks), "longest task (ms)").toBeLessThan(150);
  expect(watch.longTasks.reduce((sum, value) => sum + value, 0) / 1000 / seconds).toBeLessThan(0.15);
  const span = ((watch.commits.at(-1) ?? 0) - (watch.commits[0] ?? 0)) / 1000;
  expect(watch.commits.length / Math.max(span, 1), "reply commits per second").toBeLessThanOrEqual(25);

  // What streamed is exactly what a reload shows.
  const streamed = await lastReply(page).locator(".message-content").innerHTML();
  await page.reload();
  await expect(lastReply(page).locator(".katex-display")).toHaveCount(1);
  expect(await lastReply(page).locator(".message-content").innerHTML()).toBe(streamed);
});

test("memory stays flat over fifteen turns", async ({ page, account: _ }) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await waitForHydration(page);
  const cdp = await page.context().newCDPSession(page);
  const heap = async () => {
    await cdp.send("HeapProfiler.collectGarbage");
    return (await cdp.send("Runtime.getHeapUsage")).usedSize;
  };
  await sendAndWait(page, "Explain photosynthesis");
  const before = await heap();
  for (let turn = 0; turn < 15; turn++) await sendAndWait(page, `Question number ${turn} about the water cycle`);
  expect((await heap()) - before, "heap growth (bytes)").toBeLessThan(40 * 1024 * 1024);
});

test("the greeting: one of this week's, a new one for the next chat, word by word in one gradient", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  const first = await expectStudyGreeting(page);
  const words = emptyGreeting(page).locator("[data-greeting-word]");
  await expect(words).toHaveCount(first.split(" ").length);
  await expect(emptyGreeting(page)).toHaveAccessibleName(first); // one heading, one sentence

  // Word by word: each later word starts later.
  const delays = await words.evaluateAll((spans) => spans.map((span) => Number.parseFloat(getComputedStyle(span).animationDelay)));
  expect(delays[0]).toBe(0);
  for (let index = 1; index < delays.length; index++) expect(delays[index]).toBeGreaterThan(delays[index - 1] as number);

  // One gradient per line: every word of a line carries it at the line's width, offset by its place.
  await page.waitForTimeout(700);
  const geometry = await words.evaluateAll((spans) =>
    spans.map((span) => ({
      top: (span as HTMLElement).offsetTop,
      left: (span as HTMLElement).offsetLeft,
      size: (span as HTMLElement).style.backgroundSize,
      position: (span as HTMLElement).style.backgroundPosition,
    })),
  );
  const lines = new Map<number, typeof geometry>();
  for (const word of geometry) lines.set(word.top, [...(lines.get(word.top) ?? []), word]);
  for (const line of lines.values()) {
    expect(new Set(line.map((word) => word.size)).size, "one gradient width per line").toBe(1);
    const start = line[0]?.left ?? 0;
    for (const word of line) expect(Number.parseFloat(word.position)).toBeCloseTo(start - word.left, 0);
  }

  // The next new chat gets a different greeting.
  await sendAndWait(page, "Explain photosynthesis");
  await newChat(page);
  const second = await expectStudyGreeting(page);
  expect(second).not.toBe(first);
});

test("the greeting reads clearly in both themes and holds still with reduced motion", async ({ page, account: _ }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/");
    await waitForHydration(page);
    await expectStudyGreeting(page);
    // Every gradient stop against the page, as WCAG computes contrast.
    const ratios = await page.evaluate(() => {
      // A new element per colour: recolouring one would read the start of a (reduced-motion) transition.
      const rgb = (token: string) => {
        const probe = document.createElement("span");
        probe.style.color = `hsl(var(${token}))`;
        document.body.append(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return (color.match(/\d+(\.\d+)?/g) ?? []).slice(0, 3).map(Number);
      };
      const luminance = ([r, g, b]: number[]) =>
        [r, g, b]
          .map((value) => (value ?? 0) / 255)
          .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
          .reduce((sum, c, index) => sum + c * [0.2126, 0.7152, 0.0722][index]!, 0);
      const background = luminance(rgb("--background"));
      const ratios = Object.fromEntries(
        ["--info", "--brand", "--accent-purple"].map((token) => {
          const [light, dark] = [luminance(rgb(token)), background].sort((a, b) => b - a) as [number, number];
          return [token, (light + 0.05) / (dark + 0.05)];
        }),
      );
      return ratios;
    });
    for (const [token, ratio] of Object.entries(ratios)) expect(ratio, `${token} in ${scheme}`).toBeGreaterThanOrEqual(4.5);
    // Reduced motion: every word in place at once.
    const styles = await emptyGreeting(page)
      .locator("[data-greeting-word]")
      .evaluateAll((spans) => spans.map((span) => `${getComputedStyle(span).animationName}|${getComputedStyle(span).opacity}`));
    expect(new Set(styles)).toEqual(new Set(["none|1"]));
    await expectAccessible(page);
  }
});

test("a long chat title slides in its row, a short one does not; it holds still on hover and with reduced motion", async ({
  page,
  account: _,
}) => {
  const LONG = "A very long chat title about photosynthesis, respiration and the carbon cycle in green plants";
  const long = await seedTurn(page, "Explain photosynthesis");
  await renameChat(page, long, LONG);
  const short = await seedTurn(page, "Define osmosis");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await waitForHydration(page);

  const row = (id: string) => page.locator(`nav[aria-labelledby='chats-heading'] a[href='/c/${id}']`);
  const motion = (id: string) =>
    row(id)
      .locator(".marquee-track")
      .evaluate((element) => `${getComputedStyle(element).animationName}|${getComputedStyle(element).animationPlayState}`);
  await expect(row(short)).toHaveText("Osmosis Definition");
  await expect(row(short).locator(".marquee")).not.toHaveAttribute("data-overflowing");
  expect(await motion(short)).toBe("none|running");

  await expect(row(long)).toHaveAccessibleName(LONG); // the whole title, however it is drawn
  await expect(row(long).locator(".marquee")).toHaveAttribute("data-overflowing", "");
  expect(await motion(long)).toBe("marquee|running");
  const mask = await row(long)
    .locator(".marquee")
    .evaluate((element) => getComputedStyle(element).maskImage || getComputedStyle(element).webkitMaskImage);
  expect(mask).toContain("linear-gradient");

  await row(long).hover();
  expect(await motion(long)).toBe("marquee|paused");
  await page.mouse.move(900, 400);
  expect(await motion(long)).toBe("marquee|running");
  await row(long).focus();
  expect(await motion(long)).toBe("marquee|paused");
  await expectNoHorizontalOverflow(page);

  await page.emulateMedia({ reducedMotion: "reduce" });
  expect((await motion(long)).split("|")[0]).toBe("none");
});

test("a hostile first message names the chat in plain words only", async ({ page, account: _ }) => {
  let dialogs = 0;
  page.on("dialog", (dialog) => {
    dialogs += 1;
    void dialog.dismiss();
  });
  await page.goto("/");
  await waitForHydration(page);
  await sendAndWait(page, "Explain <img src=x onerror=alert(1)> photosynthesis [x](javascript:alert(1)) <script>alert(2)</script>");
  const title = (await heading(page).textContent()) ?? "";
  expect(title).not.toBe("New chat");
  expect(title).toMatch(/^[\p{L}\p{M}\p{N} '&-]+$/u);
  expect(title.split(" ").length).toBeLessThanOrEqual(6);
  await expect(page.locator("img[src='x']")).toHaveCount(0);
  expect(dialogs).toBe(0);
});

test("races: a double Enter sends once; a rename while the reply streams is kept; leaving mid-reply still names it", async ({
  page,
  account: _,
}) => {
  const other = await seedTurn(page, "Define osmosis");
  await page.goto("/");
  await waitForHydration(page);

  // Double Enter.
  await composer(page).fill("Explain gravity");
  await composer(page).press("Enter");
  await composer(page).press("Enter");
  await waitForIdle(page);
  await expect(page.getByRole("article", { name: "You" })).toHaveCount(1);

  // A rename while the first reply of a new chat is still streaming wins.
  await newChat(page);
  await send(page, `Explain photosynthesis ${"step by step with every detail ".repeat(12)}`);
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  const id = new URL(page.url()).pathname.split("/").pop() as string;
  const list = page.locator("nav[aria-labelledby='chats-heading']");
  await list.locator("li", { has: page.locator(`a[href="/c/${id}"]`) }).getByRole("button", { name: /^Rename/ }).click();
  const dialog = page.getByRole("dialog", { name: "Rename chat" });
  await dialog.getByLabel("Name").fill("My biology notes");
  await dialog.getByRole("button", { name: "Rename" }).click();
  await waitForIdle(page);
  await expect(heading(page)).toHaveText("My biology notes");
  await page.reload();
  await expect(heading(page)).toHaveText("My biology notes");

  // Leaving for another chat before the reply ends: it still gets its name.
  await newChat(page);
  await send(page, `What is the water cycle ${"and how does it move water around ".repeat(8)}`);
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  await page.locator(`a[href="/c/${other}"]`).click();
  await expect(heading(page)).toHaveText("Osmosis Definition");
  await expect(chatLinks(page).filter({ hasText: "Water Cycle Explained" })).toHaveCount(1, { timeout: 20_000 });
});
