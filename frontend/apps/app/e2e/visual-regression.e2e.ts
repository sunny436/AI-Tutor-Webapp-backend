import type { Locator, Page, Route } from "@playwright/test";

import {
  composer,
  expect,
  expectStudyGreeting,
  lastReply,
  renameChat,
  seedTurn,
  send,
  test,
  waitForHydration,
} from "./support";

/**
 * Pixel baselines for the chat's key states, compared with Playwright's own screenshot assertion
 * (no extra dependency): a new chat, a reply under a long chat name, a failed reply, the rail
 * collapsed and the phone's drawer, at 1440, 834 and 390 wide, light and dark.
 *
 * Stable by construction: animations off and reduced motion (the greeting's words and the sidebar
 * slide at rest), the greeting's random pick fixed, the fake model's replies, and everything that
 * differs between runs masked (message times, the account, the streak, the countdown, the bell).
 * The three dots are too brief to photograph; chat-polish.e2e.ts checks them as they happen.
 *
 * The baselines are Windows renderings (the machine releases are made from), committed next to
 * this file; fonts render differently on other systems, so there it skips. After an intended
 * change: `bunx playwright test visual-regression --update-snapshots`, then look at every image.
 */
test.skip(process.platform !== "win32", "the baselines are Windows renderings");

const WIDTHS = [1440, 834, 390];
const THEMES = ["light", "dark"] as const;
const MD = 768;
const HEIGHT = 900;
const REPLY = "Explain photosynthesis:\n\n- **light** is absorbed\n- water is split\n\n$6CO_2 + 6H_2O \\to C_6H_{12}O_6 + 6O_2$";
const LONG = "A very long chat name about photosynthesis, respiration and the carbon cycle in green plants";

function masks(page: Page): Locator[] {
  return [
    page.locator("time"),
    page.getByRole("button", { name: /^Account: / }),
    page.getByText(/@example\.com/),
  ];
}

async function snap(page: Page, name: string): Promise<void> {
  // The streak, the day's countdown and the bell change width with the time of day: give their
  // group a fixed, empty box, so nothing around it (the header's name) moves between runs.
  const width = (page.viewportSize()?.width ?? 0) < 640 ? "9rem" : "16.5rem";
  // By structure, not role: once hidden (by an earlier photo of this page) it has no role.
  const group = page.locator("header button[aria-label='Colour theme']").locator("xpath=..");
  if (await group.count()) {
    await group.evaluate(
      (element, fixed) => Object.assign((element as HTMLElement).style, { width: fixed, overflow: "hidden", visibility: "hidden" }),
      width,
    );
  }
  await page.waitForTimeout(150);
  // Soft: every state is compared (and a candidate written) in one run; any difference still fails the test.
  await expect.soft(page).toHaveScreenshot(`${name}.png`, {
    animations: "disabled",
    caret: "hide",
    mask: masks(page),
    // Same machine, same fonts: identical runs differ by 0 pixels, so a small budget catches small
    // regressions, and a low per-pixel threshold catches colour drift (the default 0.2 lets a white
    // field pass for a grey one).
    maxDiffPixels: 100,
    threshold: 0.02,
  });
}

async function failStream(route: Route): Promise<void> {
  const response = await route.fetch();
  const frames = (await response.text()).split("\n\n").filter(Boolean);
  const meta = frames.find((frame) => frame.startsWith("event: meta"));
  const { assistantMessageId } = JSON.parse(meta?.split("\ndata: ")[1] ?? "{}");
  const upTo = frames.findIndex((frame) => frame.startsWith("event: token"));
  const failure = { code: "llm_unavailable", message: "x", retryable: true, messageId: assistantMessageId, requestId: "visual" };
  await route.fulfill({ response, body: `${[...frames.slice(0, upTo + 2), `event: error\ndata: ${JSON.stringify(failure)}`].join("\n\n")}\n\n` });
}

test.beforeEach(async ({ page }) => {
  // The same greeting every run: the pick is random, so fix the random numbers.
  await page.addInitScript(() => {
    Math.random = () => 0.42;
  });
});

for (const width of WIDTHS) {
  for (const theme of THEMES) {
    test(`chat states at ${width}px, ${theme}`, async ({ page, account: _ }) => {
      test.setTimeout(90_000);
      const named = await seedTurn(page, REPLY);
      await renameChat(page, named, LONG);
      await seedTurn(page, "Define osmosis");
      await page.setViewportSize({ width, height: HEIGHT });
      await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });

      await page.goto("/");
      await waitForHydration(page);
      await expectStudyGreeting(page);
      await snap(page, `new-chat-${width}-${theme}`);

      await page.goto(`/c/${named}`);
      await expect(lastReply(page).locator(".katex")).toHaveCount(1);
      await snap(page, `reply-long-name-${width}-${theme}`);

      await page.route("**/api/v1/chat/stream", failStream);
      await send(page, "Tell me something");
      await expect(lastReply(page).getByRole("alert")).toBeVisible();
      await page.unroute("**/api/v1/chat/stream");
      await snap(page, `reply-failed-${width}-${theme}`);

      if (width >= MD) {
        await page.getByRole("button", { name: "Collapse sidebar" }).click();
        await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
        await snap(page, `rail-collapsed-${width}-${theme}`);
        await page.getByRole("button", { name: "Expand sidebar" }).click();
      } else {
        await page.goto("/");
        await expect(composer(page)).toBeVisible();
        await page.getByRole("button", { name: "Open menu" }).click();
        await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible();
        await snap(page, `drawer-${width}-${theme}`);
      }
    });
  }
}

// Around the app: Settings, the account menu, the rename dialog, a hovered long title, not-found and
// sign-in, at the widest and a phone's width, in both themes.
for (const width of [1440, 390]) {
  for (const theme of THEMES) {
    test(`around the app at ${width}px, ${theme}`, async ({ page, browser, account: _ }) => {
      test.setTimeout(90_000);
      const named = await seedTurn(page, "Explain photosynthesis");
      await renameChat(page, named, LONG);
      await page.setViewportSize({ width, height: HEIGHT });
      await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });

      await page.goto("/settings/appearance");
      await expect(page.getByRole("main").getByRole("heading", { level: 2 }).first()).toBeVisible();
      await snap(page, `settings-appearance-${width}-${theme}`);

      await page.goto("/");
      await waitForHydration(page);
      const phone = width < MD;
      if (phone) await page.getByRole("button", { name: "Open menu" }).click();
      const panel = phone ? page.getByRole("dialog", { name: "Navigation" }) : page.getByRole("complementary");
      await panel.getByRole("button", { name: /^Account: / }).click();
      await expect(page.getByRole("menu")).toBeVisible();
      await snap(page, `account-menu-${width}-${theme}`);
      await page.keyboard.press("Escape");
      await panel.getByRole("button", { name: /^Rename/ }).first().click();
      await expect(page.getByRole("dialog", { name: "Rename chat" })).toBeVisible();
      await snap(page, `rename-dialog-${width}-${theme}`);

      if (!phone) {
        // The only moment a title moves: hovered (the photo holds it at its start, fade on the right).
        await page.goto("/");
        await waitForHydration(page);
        await page.emulateMedia({ colorScheme: theme, reducedMotion: "no-preference" });
        await page.locator(`nav[aria-labelledby='chats-heading'] a[href='/c/${named}']`).hover();
        await page.waitForTimeout(500);
        await snap(page, `row-hover-${width}-${theme}`);
        await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
      }

      await page.goto("/no-such-page");
      await expect(page.getByRole("heading", { name: "This page could not be found" })).toBeVisible();
      await snap(page, `not-found-${width}-${theme}`);

      const signedOut = await browser.newPage({ viewport: { width, height: HEIGHT } });
      await signedOut.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
      await signedOut.goto("/login");
      await expect(signedOut.getByRole("button", { name: "Sign in" })).toBeVisible();
      await snap(signedOut, `sign-in-${width}-${theme}`);
      await signedOut.close();
    });
  }
}
