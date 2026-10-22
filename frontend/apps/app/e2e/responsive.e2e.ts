import type { Page } from "@playwright/test";

import {
  composer,
  expect,
  expectAccessible,
  expectNoHorizontalOverflow,
  lastReply,
  renameChat,
  seedTurn,
  sendAndWait,
  test,
} from "./support";

/**
 * The layout at every width it has to hold: 320 is WCAG's reflow width, 360-430
 * common phones, 600 and 820 small and large tablets, 767/768 straddle the `md`
 * breakpoint where the drawer gives way to the rail, 1280-1440 laptops and 1920/2560
 * large and ultrawide screens. The phone device itself (touch, DPR) is covered by
 * mobile.e2e.ts.
 */
const WIDTHS = [320, 360, 375, 390, 414, 430, 600, 767, 768, 820, 1024, 1280, 1366, 1440, 1920, 2560];
const HEIGHT = 800;
const MD = 768;
const DARK_TOO = new Set([390, 1440]);

const WIDE = [
  "A wide table and a long line of code:",
  "",
  "| Column one | Column two | Column three | Column four | Column five | Column six | Column seven |",
  "| --- | --- | --- | --- | --- | --- | --- |",
  "| a fairly long cell | another long cell | more text here | and more | and more | and more | the end |",
  "",
  "```js",
  `const veryLongLine = "${"x".repeat(200)}";`,
  "```",
].join("\n");

const LONG_TITLE =
  "A deliberately long question about quadratic equations, their discriminants and the nature of the roots";

/** The message box is inside the screen, and nothing is drawn on top of it. */
async function expectComposerUsable(page: Page, width: number): Promise<void> {
  const box = await composer(page).boundingBox();
  expect(box, "composer on screen").not.toBeNull();
  if (!box) return;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(width);
  expect(box.y + box.height).toBeLessThanOrEqual(HEIGHT);
  const uncovered = await composer(page).evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return top === element || element.contains(top);
  });
  expect(uncovered, "nothing covers the message box").toBe(true);
}

/** The page title is visible and stays inside the screen however long it is. */
async function expectTitleFits(page: Page, width: number): Promise<void> {
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toBeVisible();
  const box = await heading.boundingBox();
  expect((box?.x ?? 0) + (box?.width ?? 0), "the h1 fits the width").toBeLessThanOrEqual(width);
}

/** Below `md` navigation is a drawer behind "Open menu"; from `md` up it is the rail. */
async function expectNavigationMode(page: Page, width: number): Promise<void> {
  const openMenu = page.getByRole("button", { name: "Open menu" });
  const chats = page.locator("nav[aria-labelledby='chats-heading']");
  if (width < MD) {
    await expect(openMenu).toBeVisible();
    await expect(chats).toBeHidden();
    await openMenu.click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await expect(drawer).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(openMenu).toBeFocused();
  } else {
    await expect(openMenu).toBeHidden();
    await expect(chats).toBeVisible();
  }
}

for (const width of WIDTHS) {
  test(`at ${width}px: the chat, a wide reply, a long title and settings`, async ({ page, account: _ }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: HEIGHT });
    // Named by the student (chats are named automatically in six words or fewer).
    const titled = await seedTurn(page, LONG_TITLE);
    await renameChat(page, titled, LONG_TITLE);

    await test.step("a new chat", async () => {
      await page.goto("/");
      await expect(composer(page)).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expectComposerUsable(page, width);
      await expectTitleFits(page, width);
      await expectNavigationMode(page, width);
      await expectAccessible(page);
    });

    await test.step("a wide table and long code scroll inside the reply", async () => {
      await sendAndWait(page, WIDE);
      await expect(lastReply(page).getByRole("table")).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expectComposerUsable(page, width);
      await expectAccessible(page);
    });

    await test.step("a long chat title", async () => {
      await page.goto(`/c/${titled}`);
      await expect(lastReply(page)).toBeVisible();
      await expectTitleFits(page, width);
      await expectNoHorizontalOverflow(page);
    });

    await test.step("settings", async () => {
      await page.goto("/settings");
      await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expectAccessible(page);
    });

    if (DARK_TOO.has(width)) {
      await test.step("dark", async () => {
        await page.emulateMedia({ colorScheme: "dark" });
        await page.goto(`/c/${titled}`);
        await expect(lastReply(page)).toBeVisible();
        await expectAccessible(page);
        await page.goto("/settings");
        await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
        await expectAccessible(page);
      });
    }
  });

  test(`at ${width}px: sign-in and sign-up`, async ({ page }) => {
    await page.setViewportSize({ width, height: HEIGHT });
    const pages: [path: string, heading: string][] = [
      ["/login", "Sign in"],
      ["/signup", "Create your account"],
    ];
    for (const [path, heading] of pages) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expectAccessible(page);
      if (DARK_TOO.has(width)) {
        await page.emulateMedia({ colorScheme: "dark" });
        await expectAccessible(page);
        await page.emulateMedia({ colorScheme: "light" });
      }
    }
  });
}
