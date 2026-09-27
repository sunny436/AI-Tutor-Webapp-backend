/**
 * The learning streak, the notification bell and the chat's look, end to end: the header's 🔥
 * counts only real questions that were answered, opens Learning & Streak (calendar and day
 * details), the bell carries security alerts and is marked read, a broken streak never shows a
 * false 0, and the in-app reminder switch follows the account.
 */

import { type Page, expect } from "@playwright/test";

import { APP_URL } from "./env";
import {
  SAME_ORIGIN,
  composer,
  expectAccessible,
  expectNoHorizontalOverflow,
  lastReply,
  replies,
  sendAndWait,
  test,
  waitForHydration,
} from "./support";

const SLOGAN = "Your Questions. Your Tutor. Your Way.";
const FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0";

const banner = (page: Page) => page.getByRole("banner");
const streakBadge = (page: Page) => banner(page).getByRole("link", { name: /learning streak/i });
const bell = (page: Page) => banner(page).getByRole("button", { name: /^Notifications/ });
const stat = (page: Page, name: string) =>
  page.locator("dt", { hasText: new RegExp(`^${name}$`) }).locator("xpath=following-sibling::dd");
const todayCell = (page: Page) => page.locator('[role="button"][aria-label$=": learning day, 1 learning interaction"]');
const inAppReminders = (page: Page) => page.getByRole("switch", { name: "Reminders in the app" });

/** Today's square is within the calendar's visible width (a narrow calendar scrolls, opening at today). */
async function todayInView(page: Page): Promise<boolean> {
  return todayCell(page).evaluate((cell) => {
    const day = cell.getBoundingClientRect();
    const view = cell.closest(".learning-calendar")?.getBoundingClientRect();
    return !!view && day.left >= view.left && day.right <= view.right;
  });
}

/** The slogan in the sidebar (or the phone's drawer), measured in Poppins: lines, and inside the edge. */
async function sloganFit(page: Page) {
  await expect
    .poll(() => page.evaluate(() => [...document.fonts].some((face) => /poppins/i.test(face.family) && face.status === "loaded")))
    .toBe(true);
  await page.evaluate(() => document.fonts.ready);
  return page
    .getByText(SLOGAN, { exact: true })
    .filter({ visible: true })
    .first()
    .evaluate((element) => {
      const box = element.getBoundingClientRect();
      const edge = element.closest("aside, [role=dialog]")?.getBoundingClientRect();
      const lines = Math.round(box.height / Number.parseFloat(getComputedStyle(element).lineHeight));
      return { lines, inside: !!edge && box.right <= edge.right - 12 };
    });
}

async function preferences(page: Page) {
  return (await page.request.get(`${APP_URL}/api/v1/notifications/preferences`)).json();
}

test("the streak counts real questions only, and opens Learning & Streak with the day's details", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await waitForHydration(page);
  await expect(streakBadge(page)).toHaveAccessibleName("0 day learning streak, today's learning still to do");
  await expect(banner(page).getByText(/\d+ hours? \d+ minutes? left in today's learning day/)).toBeAttached();

  await sendAndWait(page, "hi");
  await expect(streakBadge(page)).toHaveAccessibleName("0 day learning streak, today's learning still to do");

  await sendAndWait(page, "What is photosynthesis?");
  await expect(streakBadge(page)).toHaveAccessibleName("1 day learning streak");
  const api = await (await page.request.get(`${APP_URL}/api/v1/progress/streak`)).json();
  expect(api).toMatchObject({ currentStreak: 1, longestStreak: 1, todayActive: true, timezone: "Asia/Kolkata" });

  await streakBadge(page).click();
  await expect(page).toHaveURL("/settings/streak");
  await expect(page.getByRole("heading", { level: 2, name: "Learning & Streak" })).toBeVisible();
  await expect(stat(page, "Current streak")).toHaveText("1 day");
  await expect(stat(page, "Longest streak")).toHaveText("1 day");
  await expect(stat(page, "Today's learning")).toHaveText("Completed");

  await expect(todayCell(page)).toHaveCount(1);
  await expect.poll(() => todayInView(page)).toBe(true);
  await todayCell(page).click();
  await expect(page.getByText("✓ Learning day · 1 learning interaction")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expectAccessible(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
});

test("the bell shows a new sign-in, and opening it marks it read", async ({ page, browser, account }) => {
  await page.goto("/");
  await waitForHydration(page);
  await expect(bell(page)).toHaveAccessibleName("Notifications");

  const other = await browser.newContext({ baseURL: APP_URL });
  const login = await other.request.post("/api/v1/auth/login", {
    data: { email: account.email, password: account.password },
    headers: { ...SAME_ORIGIN, "User-Agent": FIREFOX },
  });
  expect(login.status()).toBe(200);
  await other.close();

  await page.reload();
  await expect(bell(page)).toHaveAccessibleName("Notifications, 1 unread");
  await bell(page).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByText("New sign-in to your account")).toBeVisible();
  await expect(menu.getByText(/^Firefox on Linux, /)).toBeVisible();
  await expectAccessible(page);
  await page.keyboard.press("Escape");
  await expect(bell(page)).toHaveAccessibleName("Notifications"); // the menu hides the page while open
  await expect
    .poll(async () => (await (await page.request.get(`${APP_URL}/api/v1/notifications`)).json()).unreadCount)
    .toBe(0);
});

test("a streak that can't be read shows –, never 0, and the chat still works", async ({ page, account: _ }) => {
  const down = { status: 503, contentType: "application/json", body: '{"error":{"code":"x","message":"Down","requestId":"x"}}' };
  await page.route("**/api/v1/progress/streak", (route) => route.fulfill(down));
  await page.route("**/api/v1/notifications", (route) => route.fulfill(down));
  await page.goto("/");
  await waitForHydration(page);
  await expect(streakBadge(page)).toHaveAccessibleName("Learning streak unavailable");
  await expect(streakBadge(page)).toHaveText("–");
  await sendAndWait(page, "Explain Newton's second law");
  await expect(lastReply(page)).toContainText(/\S/);
  await bell(page).click();
  await expect(page.getByText("Couldn't load notifications.")).toBeVisible();
});

test("reminders in the app: the switch saves, and stays off after a reload and on another device", async ({
  page,
  browser,
  account,
}) => {
  await page.goto("/settings/notifications");
  await expect(inAppReminders(page)).toBeChecked();
  await inAppReminders(page).click();
  await expect.poll(async () => (await preferences(page)).inAppReminders).toBe(false);
  await page.reload();
  await expect(inAppReminders(page)).not.toBeChecked();

  const context = await browser.newContext({ baseURL: APP_URL });
  const login = await context.request.post("/api/v1/auth/login", {
    data: { email: account.email, password: account.password },
    headers: SAME_ORIGIN,
  });
  expect(login.status()).toBe(200);
  const other = await context.newPage();
  await other.goto("/settings/notifications");
  await expect(inAppReminders(other)).not.toBeChecked();
  await inAppReminders(other).click();
  await expect.poll(async () => (await preferences(other)).inAppReminders).toBe(true);
  await context.close();
  await page.reload();
  await expect(inAppReminders(page)).toBeChecked();
});

test("the look: Poppins everywhere, the slogan on one line, and a clean chat", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  expect(await page.locator("body").innerText()).not.toMatch(/AI Tutor India/i);
  await expect(page.getByRole("complementary").getByText(SLOGAN, { exact: true })).toBeVisible();
  expect(await sloganFit(page), "the slogan is one line inside the sidebar").toEqual({ lines: 1, inside: true });
  await sendAndWait(page, "What is a prime number?");

  const fonts = await page.evaluate(() =>
    [
      document.body,
      document.querySelector("header"),
      document.querySelector("nav"),
      document.querySelector("textarea"),
      document.querySelector('article[aria-label="Assistant"]'),
      document.querySelector('article[aria-label="You"]'),
      document.querySelector("button"),
    ].map((element) => (element ? getComputedStyle(element).fontFamily : "missing")),
  );
  for (const family of fonts) expect(family).toMatch(/Poppins/i);

  // The reply sits on the page (no card), the student's message is a neutral bubble, one composer box.
  const look = await page.evaluate(() => {
    const reply = document.querySelector('article[aria-label="Assistant"] div.min-w-0 > div');
    const bubble = document.querySelector('article[aria-label="You"] > div');
    const surface = getComputedStyle(document.documentElement).getPropertyValue("--surface-2").trim();
    const probe = document.createElement("div");
    probe.style.backgroundColor = `hsl(${surface.split(/\s+/).join(", ")})`;
    document.body.append(probe);
    const expected = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return {
      replyBorder: reply ? getComputedStyle(reply).borderTopWidth : "missing",
      replyBackground: reply ? getComputedStyle(reply).backgroundColor : "missing",
      bubble: bubble ? getComputedStyle(bubble).backgroundColor : "missing",
      expected,
      forms: document.querySelectorAll("form:has(textarea)").length,
    };
  });
  expect(look.replyBorder).toBe("0px");
  expect(look.replyBackground).toBe("rgba(0, 0, 0, 0)");
  expect(look.bubble).toBe(look.expected);
  expect(look.forms).toBe(1);
  await expect(replies(page)).toHaveCount(1);
  await expect(composer(page)).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expectAccessible(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
});

test("a phone at 320 px: the header, the chat and Learning & Streak fit", async ({ page, account: _ }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto("/");
  await waitForHydration(page);
  await expect(streakBadge(page)).toBeVisible();
  await expect(bell(page)).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Open menu" }).click();
  expect(await sloganFit(page), "the slogan is one line in the 272px drawer").toEqual({ lines: 1, inside: true });
  await page.keyboard.press("Escape");
  await sendAndWait(page, "What is the speed of light?");
  await expectNoHorizontalOverflow(page);
  await page.goto("/settings/streak");
  await expect(page.getByRole("heading", { level: 2, name: "Learning & Streak" })).toBeVisible();
  await expect(todayCell(page)).toHaveCount(1);
  await expect.poll(() => todayInView(page)).toBe(true);
  await expectNoHorizontalOverflow(page);
  await page.emulateMedia({ colorScheme: "dark" });
  // Redrawn for the dark theme: still a labelled group with one Tab stop.
  await expect(page.locator('svg.calendar-heatmap[role="group"] rect.day-cell[tabindex="0"]')).toHaveCount(1);
  await expectAccessible(page);
});
