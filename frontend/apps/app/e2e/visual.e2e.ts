import { join } from "node:path";
import type { Locator, Page, Route } from "@playwright/test";

import { PREVIEW_URL } from "./env";
import { LONG_MESSAGE, composer, expect, lastReply, seedTurn, send, stopButton, test, waitForIdle } from "./support";

/**
 * VISUAL CAPTURE, not a pixel test. Photographs every screen that matters at three
 * widths in both themes, for a person to compare before and after a visual change
 * (a design-token change touches every screen at once). It asserts nothing about
 * pixels: the app uses the platform's own fonts, so a stored baseline taken on one
 * machine would fail on every other.
 *
 *   E2E_VISUAL=1 E2E_VISUAL_DIR=/abs/dir bun run test:e2e e2e/visual.e2e.ts
 *
 * Tool pages that only exist with PREVIEW_FEATURES=1 are captured too when the
 * preview server (:3101, started by serve.mjs) is up.
 */
test.skip(!process.env.E2E_VISUAL, "capture only: set E2E_VISUAL=1");

const DIR = process.env.E2E_VISUAL_DIR ?? join(__dirname, "..", "test-results", "visual");
const WIDTHS = [390, 768, 1280];
const THEMES = ["light", "dark"] as const;
const HEIGHT = 860;
const MD = 768;
const TOOL_PAGES = ["homework", "summarizer"];

const MARKDOWN = [
  "## Quadratic equations",
  "",
  "Here is **bold**, *italic*, `inline code` and a [link](https://example.com).",
  "",
  "| Name | Value |",
  "| --- | --- |",
  "| alpha | 1 |",
  "| beta | 2 |",
  "",
  "```python",
  "def roots(a, b, c):",
  "    d = b * b - 4 * a * c",
  "    return d",
  "```",
  "",
  "Inline math $a^2 + b^2 = c^2$ and a block:",
  "",
  "$$",
  "x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}",
  "$$",
].join("\n");

type Shot = (name: string) => Promise<void>;

function matrix(run: (width: number, theme: (typeof THEMES)[number], shot: Shot) => Promise<void>, page: Page) {
  return async () => {
    for (const width of WIDTHS) {
      for (const theme of THEMES) {
        await page.setViewportSize({ width, height: HEIGHT });
        await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
        const shot: Shot = async (name) => {
          await page.waitForTimeout(200);
          await page.screenshot({ path: join(DIR, `${name}--${width}-${theme}.png`) });
        };
        await run(width, theme, shot);
      }
    }
  };
}

/** Where the chat list is: the rail from `md` up, the drawer below it. */
async function openList(page: Page, width: number): Promise<Page | Locator> {
  if (width >= MD) return page;
  await page.getByRole("button", { name: "Open menu" }).click();
  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await expect(drawer).toBeVisible();
  return drawer;
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

test("signed out: sign-in, sign-up, verify and reset", async ({ page }) => {
  test.setTimeout(180_000);
  await matrix(async (_width, _theme, shot) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await shot("auth-sign-in");
    await page.getByRole("button", { name: "Forgot password?" }).click();
    await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
    await shot("auth-forgot");
    await page.goto("/signup");
    await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
    await shot("auth-sign-up");
    await page.getByRole("button", { name: "I have a code" }).click();
    await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
    await shot("auth-verify");
  }, page)();
});

test("signed in: the chat, its states, dialogs, settings and the 404", async ({ page, account: _ }) => {
  test.setTimeout(600_000);
  const rich = await seedTurn(page, MARKDOWN);
  const failing = await seedTurn(page, "A chat whose next reply fails");
  await page.goto("/");
  await send(page, LONG_MESSAGE);
  await expect(lastReply(page)).toContainText("w5");
  await stopButton(page).click();
  await waitForIdle(page);
  const stopped = new URL(page.url()).pathname;
  const preview = await fetch(`${PREVIEW_URL}/login`).then((response) => response.ok, () => false);

  await matrix(async (width, _theme, shot) => {
    await page.goto("/");
    await expect(composer(page)).toBeVisible();
    await shot("chat-new");

    await page.goto(`/c/${rich}`);
    await expect(lastReply(page).getByRole("table")).toBeVisible();
    await expect(lastReply(page).locator(".katex-display")).toHaveCount(1);
    await shot("chat-rich-reply");

    await page.goto(stopped);
    await expect(lastReply(page)).toContainText("Stopped");
    await shot("chat-stopped");

    await page.goto(`/c/${failing}`);
    await expect(lastReply(page)).toBeVisible();
    await page.route("**/api/v1/chat/stream", failStream);
    await send(page, "Tell me something");
    await expect(lastReply(page).getByRole("alert")).toBeVisible();
    await shot("chat-error");
    await page.unroute("**/api/v1/chat/stream");

    await page.goto("/c/00000000-0000-4000-8000-000000000000");
    await expect(page.getByRole("heading", { name: "This chat isn't available" })).toBeVisible();
    await shot("chat-unavailable");

    await page.goto("/");
    const list = await openList(page, width);
    const row = list.locator("li", { has: page.locator(`a[href="/c/${rich}"]`) });
    await row.getByRole("button", { name: /^Rename/ }).click();
    await expect(page.getByRole("dialog", { name: "Rename chat" })).toBeVisible();
    await shot("dialog-rename");
    // Start clean rather than unwinding nested dialogs (a dialog over the drawer) key by key.
    await page.goto("/");
    await expect(composer(page)).toBeVisible();

    const again = await openList(page, width);
    await again
      .locator("li", { has: page.locator(`a[href="/c/${rich}"]`) })
      .getByRole("button", { name: /^Delete/ })
      .click();
    await expect(page.getByRole("dialog", { name: "Delete this chat?" })).toBeVisible();
    await shot("dialog-delete-chat");
    await page.goto("/");
    await expect(composer(page)).toBeVisible();

    if (width < MD) {
      await openList(page, width);
      await shot("nav-drawer");
      await page.keyboard.press("Escape");
    } else {
      await page.getByRole("button", { name: "Collapse sidebar" }).click();
      await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
      await shot("nav-rail-collapsed");
      await page.getByRole("button", { name: "Expand sidebar" }).click();
    }

    await page.goto("/settings");
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    await shot("settings");
    await page.getByRole("button", { name: "Delete account" }).click();
    await expect(page.getByRole("dialog", { name: "Delete your account?" })).toBeVisible();
    await shot("dialog-delete-account");
    await page.keyboard.press("Escape");

    await page.goto("/no-such-page");
    await expect(page.getByRole("heading", { name: "This page could not be found" })).toBeVisible();
    await shot("not-found");

    if (preview) {
      await page.goto(`${PREVIEW_URL}/`);
      await expect(composer(page)).toBeVisible();
      await shot("preview-chat-new");
      for (const tool of TOOL_PAGES) {
        await page.goto(`${PREVIEW_URL}/${tool}`);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await shot(`preview-${tool}`);
      }
    }
  }, page)();
});
