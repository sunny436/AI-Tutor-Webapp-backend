import type { Page } from "@playwright/test";

import { LONG_MESSAGE, expect, lastReply, send, sendAndWait, test, waitForIdle } from "./support";

const scroller = (page: Page) => page.locator("section[aria-label='Conversation']").locator("..");

/** How far the transcript is from its bottom edge, in px. */
const distanceFromBottom = (page: Page) =>
  scroller(page).evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight);

/** Forty short paragraphs: a reply several screens tall that takes ~6 s to stream. */
const TALL_MESSAGE = Array.from({ length: 40 }, (_, index) => `Paragraph ${index + 1}.`).join("\n\n");

test("a streamed token changes only the reply being written", async ({ page, account: _ }) => {
  await page.goto("/");
  await sendAndWait(page, "Something to scroll past");
  await send(page, LONG_MESSAGE);
  await expect(lastReply(page)).toContainText("w3");

  // Watch the whole transcript and the sidebar for 1.5 s of streaming.
  const seen = await page.evaluate(async () => {
    const transcript = document.querySelector("section[aria-label='Conversation']") as HTMLElement;
    const sidebar = document.querySelector("nav[aria-labelledby='chats-heading']") as HTMLElement;
    const articles = transcript.querySelectorAll("article");
    const writing = articles[articles.length - 1] as HTMLElement;
    const elsewhere: string[] = [];
    let inside = 0;
    let sidebarChanges = 0;
    const describe = (node: Node) => {
      const element = node instanceof Element ? node : node.parentElement;
      return `${element?.tagName ?? "?"} in ${element?.closest("article")?.getAttribute("aria-label") ?? "no article"}`;
    };
    const transcriptObserver = new MutationObserver((records) => {
      for (const record of records) {
        if (writing.contains(record.target)) inside += 1;
        else elsewhere.push(`${record.type}: ${describe(record.target)}`);
      }
    });
    const sidebarObserver = new MutationObserver((records) => {
      sidebarChanges += records.length;
    });
    const options = { subtree: true, childList: true, characterData: true, attributes: true };
    transcriptObserver.observe(transcript, options);
    sidebarObserver.observe(sidebar, options);
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    transcriptObserver.disconnect();
    sidebarObserver.disconnect();
    return { inside, elsewhere, sidebarChanges, stillWriting: writing.getAttribute("aria-busy") === "true" };
  });

  expect(seen.stillWriting, "the reply was still streaming throughout").toBe(true);
  expect(seen.inside, "the streaming reply changed").toBeGreaterThan(0);
  expect(seen.elsewhere, "nothing else in the transcript changed").toEqual([]);
  expect(seen.sidebarChanges, "the sidebar did not change").toBe(0);
  await waitForIdle(page);
});

test("the view follows a reply only while the reader is at the bottom", async ({ page, account: _ }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.goto("/");

  await test.step("at the bottom: it follows the reply down", async () => {
    await send(page, TALL_MESSAGE);
    await expect(lastReply(page)).toContainText("Paragraph 12.");
    for (let sample = 0; sample < 5; sample += 1) {
      expect(await distanceFromBottom(page)).toBeLessThanOrEqual(80);
      await page.waitForTimeout(250);
    }
    await waitForIdle(page);
    expect(await distanceFromBottom(page)).toBeLessThanOrEqual(80);
  });

  await test.step("scrolled up: it stays put, and offers a way back", async () => {
    await send(page, TALL_MESSAGE);
    await expect(lastReply(page)).toContainText("Paragraph 5.");
    const box = await scroller(page).boundingBox();
    if (!box) throw new Error("no transcript on screen");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, -1500);
    await expect(page.getByRole("button", { name: "Jump to latest" })).toBeVisible();

    const top = await scroller(page).evaluate((element) => element.scrollTop);
    await page.waitForTimeout(1_000); // still streaming
    await expect(lastReply(page)).toHaveAttribute("aria-busy", "true");
    expect(await scroller(page).evaluate((element) => element.scrollTop)).toBe(top);

    await page.getByRole("button", { name: "Jump to latest" }).click();
    await expect.poll(() => distanceFromBottom(page)).toBeLessThanOrEqual(80);
    await waitForIdle(page);
    expect(await distanceFromBottom(page)).toBeLessThanOrEqual(80);
  });
});
