import type { Page } from "@playwright/test";

import { backendDir, sql } from "./db";
import {
  LONG_MESSAGE,
  PASSWORD,
  accountMenu,
  composer,
  emptyGreeting,
  expect,
  expectNoHorizontalOverflow,
  expectStudyGreeting,
  lastReply,
  logOutFromSidebar,
  openSettingsFromSidebar,
  stopButton,
  test,
  waitForHydration,
  waitForIdle,
} from "./support";

/**
 * The new chat (a study greeting and ONE centred composer that moves to the bottom on the first
 * message), the header's theme menu, the sidebar's account menu, and opening Settings while a new
 * chat's first reply is still starting on a slow server.
 */

const STREAM = "**/api/v1/chat/stream";
const PROBE = "the one composer";

/** Where the composer is, against the main area; and whether the page itself ever scrolled. */
async function layout(page: Page) {
  return page.evaluate(() => {
    const main = (document.getElementById("main") as HTMLElement).getBoundingClientRect();
    const form = (document.querySelector("form:has(textarea)") as HTMLElement).getBoundingClientRect();
    const transcript = (document.querySelector("section[aria-label='Conversation']")?.parentElement as HTMLElement).getBoundingClientRect();
    return {
      centred: Math.abs(form.top + form.height / 2 - (main.top + main.height / 2)) < main.height * 0.1,
      atBottom: main.bottom - form.bottom < 64,
      clearOfTranscript: form.top >= transcript.bottom - 1,
      pageScroll: document.scrollingElement?.scrollTop ?? 0,
    };
  });
}

/** Mark the composer's DOM node, then check it is still the same, and the only one. */
const mark = (page: Page) => composer(page).evaluate((element, probe) => Object.assign(element, { __probe: probe }), PROBE);
async function sameComposer(page: Page) {
  await expect(composer(page)).toHaveCount(1);
  expect(await composer(page).evaluate((element) => (element as unknown as { __probe?: string }).__probe)).toBe(PROBE);
}

async function sendWithEnter(page: Page, text: string) {
  await composer(page).fill(text);
  await composer(page).press("Enter");
}

test("a new chat: this week's study greeting, the composer centred, then ONE composer through a whole chat", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  await expectStudyGreeting(page);
  await expect(page.getByRole("list", { name: "Suggested questions" })).toHaveCount(0);
  // Attach, Voice mode (the e2e API offers it), Send and (where the browser can dictate) Dictate; nothing else.
  await expect(page.getByRole("button", { name: "Voice mode" })).toBeVisible();
  const buttons = await page.getByRole("main").getByRole("button").evaluateAll((all) => all.map((b) => b.getAttribute("aria-label")));
  expect(buttons.filter((name) => name !== "Dictate")).toEqual(["Attach files", "Voice mode", "Send message"]);
  expect(await layout(page)).toMatchObject({ centred: true, pageScroll: 0 });
  await mark(page);

  // A short first message: the composer glides to the bottom; the chat gets its address.
  await sendWithEnter(page, "Hi");
  await expect(composer(page)).toBeFocused();
  await expect(emptyGreeting(page)).toHaveCount(0);
  await expect.poll(async () => (await layout(page)).atBottom).toBe(true);
  await waitForIdle(page);
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  await sameComposer(page);

  // A long one, stopped mid-reply, then another.
  await sendWithEnter(page, LONG_MESSAGE);
  await expect(stopButton(page)).toBeVisible();
  await stopButton(page).click();
  await waitForIdle(page);
  await sendWithEnter(page, "And one more question");
  await waitForIdle(page);
  await expect(lastReply(page)).toContainText("You said: And one more question");
  await sameComposer(page);
  expect(await layout(page)).toMatchObject({ atBottom: true, clearOfTranscript: true, pageScroll: 0 });

  // A reload is a new page: the chat is there, the composer at the bottom.
  await page.reload();
  await waitForHydration(page);
  expect(await layout(page)).toMatchObject({ atBottom: true, pageScroll: 0 });
});

test("a failed first message comes back into the same centred composer; a slow one moves it at once", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  await mark(page);

  await page.route(STREAM, (route) => route.abort("internetdisconnected"));
  await sendWithEnter(page, "Are you there?");
  await expect(page.getByRole("alert").filter({ hasText: "You're offline" })).toBeVisible();
  await expect(composer(page)).toHaveValue("Are you there?");
  await expect(emptyGreeting(page)).toBeVisible();
  await expect.poll(async () => (await layout(page)).centred).toBe(true);
  await sameComposer(page);
  await page.unroute(STREAM);

  await page.route(
    STREAM,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    },
    { times: 1 },
  );
  await sendWithEnter(page, "Are you there?");
  await expect.poll(async () => (await layout(page)).atBottom, { timeout: 1000 }).toBe(true);
  await waitForIdle(page);
  await expect(lastReply(page)).toContainText("You said: Are you there?");
  await sameComposer(page);
});

test("the first message makes the composer glide down, frame by frame, not jump", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  await composer(page).fill("Hi");
  // Its top edge, every frame for 600 ms from the moment Enter is pressed.
  const tops = page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const form = document.querySelector("form:has(textarea)") as HTMLElement;
        const seen: number[] = [];
        const start = performance.now();
        const sample = () => {
          seen.push(Math.round(form.getBoundingClientRect().top));
          if (performance.now() - start < 600) requestAnimationFrame(sample);
          else resolve(seen);
        };
        requestAnimationFrame(sample);
      }),
  );
  await composer(page).press("Enter");
  const positions = await tops;
  const first = positions[0] as number;
  const last = positions.at(-1) as number;
  expect(last - first, "it ends further down").toBeGreaterThan(100);
  const between = new Set(positions.filter((top) => top > first + 2 && top < last - 2));
  expect(between.size, "positions on the way down").toBeGreaterThanOrEqual(3);
  expect(positions.every((top, index) => index === 0 || top >= (positions[index - 1] as number)), "never back up").toBe(true);
  await waitForIdle(page);
});

test("with reduced motion the composer moves without animating", async ({ page, account: _ }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await waitForHydration(page);
  const duration = await page
    .locator("[data-composer-spacer]")
    .evaluate((element) => Number.parseFloat(getComputedStyle(element).transitionDuration));
  expect(duration).toBeLessThan(0.001);
  await sendWithEnter(page, "Hi");
  await page.waitForTimeout(60);
  expect((await layout(page)).atBottom).toBe(true);
  await waitForIdle(page);
});

test("no study greeting live this week: the fallback, and the chat works as ever", async ({ page, account: _ }) => {
  test.skip(!backendDir, "needs the local backend's database");
  sql("UPDATE study_greetings SET active_from = active_from + 700"); // 100 weeks on, Mondays kept
  try {
    await page.goto("/");
    await waitForHydration(page);
    await expect(emptyGreeting(page)).toHaveText("What are you studying today?");
    await sendWithEnter(page, "Hello there");
    await waitForIdle(page);
    await expect(lastReply(page)).toContainText("You said: Hello there");
  } finally {
    sql("UPDATE study_greetings SET active_from = active_from - 700");
  }
});

test("the theme menu: Light, Dark, System with a check; saved to the account; keyboard and outside click", async ({
  page,
  account,
}) => {
  const html = page.locator("html");
  const trigger = page.getByRole("banner").getByRole("button", { name: "Colour theme" });
  await page.goto("/");
  await waitForHydration(page);
  await expect(trigger).toHaveAttribute("aria-haspopup", "menu");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await trigger.click();
  const items = page.getByRole("menuitemradio");
  await expect(items).toHaveText(["Light", "Dark", "System"]);
  await expect(page.getByRole("menuitemradio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("menuitemradio", { name: "Dark" }).click();
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(html).toHaveClass(/\bdark\b/);
  await expect.poll(async () => (await (await page.request.get("/api/v1/me/appearance")).json()).theme).toBe("dark");

  await page.reload();
  await waitForHydration(page);
  await expect(html).toHaveClass(/\bdark\b/);
  await expect(trigger.locator("svg")).toHaveClass(/lucide-moon/);
  await trigger.click();
  await expect(page.getByRole("menuitemradio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.mouse.click(10, 400); // outside
  await expect(page.getByRole("menu")).toHaveCount(0);

  // The account keeps it: signed out and in again, still dark.
  await logOutFromSidebar(page);
  await expect(page).toHaveURL("/login");
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password ?? PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");
  await expect(html).toHaveClass(/\bdark\b/);
});

test("the account menu, by keyboard: named, expands, arrows, Escape gives focus back, Settings and Log out", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  const trigger = page.getByRole("complementary").getByRole("button", { name: /^Account: / });
  await expect(page.getByRole("complementary").getByRole("link", { name: "Settings" })).toHaveCount(0);
  await expect(page.getByRole("complementary").getByRole("button", { name: "Log out" })).toHaveCount(0);
  await expect(trigger).toHaveAttribute("aria-haspopup", "menu");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("menuitem")).toHaveText(["Settings", "Log out"]);
  await expect(page.getByRole("menuitem", { name: "Settings" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Log out" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "Settings" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/settings/profile");

  await page.goto("/");
  await waitForHydration(page);
  await trigger.focus();
  await page.keyboard.press("Enter");
  // Each key once the menu has moved focus: a key pressed before it opened is not the menu's.
  await expect(page.getByRole("menuitem", { name: "Settings" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Log out" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/login");
});

for (const width of [320, 375]) {
  test(`at ${width}px: the account menu over the phone drawer, the theme menu at the edge, both in view`, async ({
    page,
    account: _,
  }) => {
    await page.setViewportSize({ width, height: 700 });
    await page.goto("/");
    await waitForHydration(page);
    const inView = async () => {
      const box = await page.getByRole("menu").boundingBox();
      expect(box).not.toBeNull();
      if (!box) return;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      expect(box.y + box.height).toBeLessThanOrEqual(700);
    };

    await page.getByRole("button", { name: "Open menu" }).click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await accountMenu(page, drawer);
    await inView();
    await page.keyboard.press("Escape"); // the menu first...
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("button", { name: /^Account: / })).toBeFocused();
    await page.keyboard.press("Escape"); // ...then the drawer
    await expect(drawer).toHaveCount(0);

    await page.getByRole("banner").getByRole("button", { name: "Colour theme" }).click();
    await inView();
    await page.keyboard.press("Escape");
    await expectNoHorizontalOverflow(page);
  });
}

test("a menu opened while a new chat gets its address stays open, with focus in it", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  // The reply's first event, which gives the chat its address, comes 1.5 s after sending.
  await page.route(
    STREAM,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.continue();
    },
    { times: 1 },
  );
  await composer(page).fill("A first question, then the account menu");
  await page.getByRole("button", { name: "Send message" }).click();
  const menu = await accountMenu(page);
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/, { timeout: 15_000 });
  await page.waitForTimeout(500);
  await expect(menu).toBeVisible();
  expect(await menu.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await expect(composer(page)).not.toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await waitForIdle(page);
});

test("Settings opened while a new chat's first reply starts, on a slow server, stays open; Close comes back to the chat", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  // The reply begins (the chat gets its id) while the Settings page is still loading.
  await page.route(
    STREAM,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.continue();
    },
    { times: 1 },
  );
  await page.route(/\/settings\/profile\?_rsc=/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    await route.continue();
  });
  await composer(page).fill("A question, then straight to Settings");
  await page.getByRole("button", { name: "Send message" }).click();
  await openSettingsFromSidebar(page);

  await expect(page).toHaveURL("/settings/profile", { timeout: 15_000 });
  await page.waitForTimeout(2000); // and it stays there
  await expect(page).toHaveURL("/settings/profile");

  await page.getByRole("link", { name: "Close settings" }).click();
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  await waitForIdle(page);
  await expect(lastReply(page)).toContainText("You said: A question, then straight to Settings");
});
