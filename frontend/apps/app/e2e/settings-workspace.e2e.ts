/**
 * Settings as its own workspace: how it is entered and left, how it moves between sections
 * (links, search, Back and Forward), what protects an unsaved edit, where focus and scroll go,
 * what happens when the session ends or the network is slow, and how it fits around the
 * desktop/phone boundary (768px). Runs on Chromium and WebKit (playwright.config.ts).
 */

import { type Page, expect } from "@playwright/test";

import { APP_URL } from "./env";
import {
  LONG_MESSAGE,
  SAME_ORIGIN,
  composer,
  describeFocus,
  expectAccessible,
  expectNoHorizontalOverflow,
  lastReply,
  openSettingsFromSidebar,
  seedTurn,
  send,
  stopButton,
  test,
  waitForHydration,
} from "./support";

const SECTIONS = [
  ["profile", "Profile"],
  ["academic", "Academic Profile"],
  ["goals", "Learning Goals"],
  ["learning", "Learning Preferences"],
  ["tutor", "AI Tutor"],
  ["subjects", "Subjects & Study"],
  ["progress", "Progress & Goals"],
  ["study-tracking", "Study Tracking"],
  ["streak", "Learning & Streak"],
  ["notifications", "Notifications"],
  ["appearance", "Appearance & Accessibility"],
  ["privacy", "Privacy & Security"],
  ["help", "Help & Support"],
] as const;

const panel = (page: Page) => page.getByRole("complementary", { name: "Settings" });
const sections = (page: Page) => page.getByRole("navigation", { name: "Settings sections" });
const section = (page: Page, name: string) => sections(page).getByRole("link", { name, exact: true });
const closeSettings = (page: Page) => page.getByRole("link", { name: "Close settings" });
const search = (page: Page) => page.getByRole("searchbox", { name: "Search settings" });
const title = (page: Page) => page.getByRole("heading", { level: 1, name: "Settings" });
const heading = (page: Page, name: string) => page.getByRole("heading", { level: 2, name, exact: true });

/** Nothing inside the section's scrolling area is wider than it. */
async function expectNoInnerOverflow(page: Page) {
  const overflow = await page.locator("main").evaluate((main) => main.scrollWidth - main.clientWidth);
  expect(overflow, `content wider than <main> on ${page.url()}`).toBeLessThanOrEqual(0);
}

/** The next dialog (confirm) gets this answer; returns what it asked. */
function answerNext(page: Page, accept: boolean): Promise<string> {
  return new Promise((resolve) => {
    page.once("dialog", async (dialog) => {
      resolve(dialog.message());
      await (accept ? dialog.accept() : dialog.dismiss());
    });
  });
}

// ------------------------------------------------------------------ entering and leaving

test("opened from a chat: the app shell steps aside, focus is on the section, Close comes back", async ({
  page,
  account: _,
  browserName,
}) => {
  const id = await seedTurn(page, "A chat to come back to");
  await page.goto(`/c/${id}`);
  await expect(lastReply(page)).toBeVisible();

  await openSettingsFromSidebar(page);
  await expect(page).toHaveURL("/settings/profile");
  await expect(title(page)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Learning Hub" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Recent Doubts" })).toHaveCount(0);
  await expect(panel(page)).toBeVisible();
  await expect(section(page, "Profile")).toHaveAttribute("aria-current", "page");
  await expect(heading(page, "Profile")).toBeFocused();
  await expect(closeSettings(page)).toHaveAttribute("href", `/c/${id}`);
  await expectAccessible(page);

  // A category: the panel stays, and focus is never lost. Where the engine focuses a clicked
  // link (Chromium, WebKit on Linux) it stays on the category; where it doesn't (WebKit on
  // Windows and Apple platforms) it goes to the section's heading.
  await section(page, "Notifications").click();
  await expect(page).toHaveURL("/settings/notifications");
  await expect(heading(page, "Notifications")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const active = document.activeElement;
        if (active?.matches('nav[aria-label="Settings sections"] a[href="/settings/notifications"]')) return "category";
        if (active?.matches("[data-settings-heading]")) return "heading";
        return active?.tagName ?? "none";
      }),
    )
    .toMatch(browserName === "webkit" ? /^(category|heading)$/ : /^category$/);

  await closeSettings(page).click();
  await expect(page).toHaveURL(`/c/${id}`);
  await expect(lastReply(page)).toBeVisible();
  await expect(composer(page)).toBeFocused();
});

test("opened from another app page, Close returns there with focus on its title", async ({ page, account: _ }) => {
  await page.goto("/help");
  await openSettingsFromSidebar(page);
  await expect(page).toHaveURL("/settings/profile");
  await closeSettings(page).click();
  await expect(page).toHaveURL("/help");
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeFocused();
});

test("every section has its own address and title; with nowhere to return to, Close goes home", async ({ browser, account }) => {
  // A fresh browser: nothing remembered.
  const context = await browser.newContext({ baseURL: APP_URL });
  const page = await context.newPage();
  const login = await context.request.post("/api/auth/sign-in/email", {
    data: { email: account.email, password: account.password },
    headers: SAME_ORIGIN,
  });
  expect(login.status()).toBe(200);
  for (const [slug, name] of SECTIONS) {
    await page.goto(`/settings/${slug}`);
    await expect(heading(page, name)).toBeVisible();
    await expect(page).toHaveTitle(`${name} · Settings · PadhAI`);
    await expect(section(page, name)).toHaveAttribute("aria-current", "page");
  }
  await expect(heading(page, "Help & Support")).not.toBeFocused(); // a fresh load never moves focus
  await closeSettings(page).click();
  await expect(page).toHaveURL("/");
  // An unknown section is a real 404, not a page that says so with a 200.
  for (const unknown of ["/settings/nothing-here", "/settings/PRIVACY", "/settings/privacy/extra"]) {
    expect((await page.goto(unknown))?.status(), unknown).toBe(404);
    await expect(page.getByRole("heading", { name: "This page could not be found" })).toBeVisible();
  }
  await context.close();
});

test("/settings opens the first section on a wide screen, without a Back loop", async ({ page, account: _ }) => {
  await page.goto("/help");
  await page.goto("/settings");
  await expect(page).toHaveURL("/settings/profile");
  await expect(page).toHaveTitle("Profile · Settings · PadhAI");
  await page.goBack();
  await expect(page).toHaveURL("/help");
});

test("Back and Forward walk the sections, then back out to the app", async ({ page, account: _ }) => {
  await page.goto("/help");
  await openSettingsFromSidebar(page);
  await expect(page).toHaveURL("/settings/profile");
  await section(page, "Notifications").click();
  await expect(heading(page, "Notifications")).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL("/settings/profile");
  await expect(heading(page, "Profile")).toBeVisible();
  await expect(section(page, "Profile")).toHaveAttribute("aria-current", "page");
  await page.goBack();
  await expect(page).toHaveURL("/help");
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL("/settings/profile");
  await page.goForward();
  await expect(page).toHaveURL("/settings/notifications");
  await expect(heading(page, "Notifications")).toBeVisible();
});

// ------------------------------------------------------------------ unsaved edits

test("an unsaved edit is asked about on every way out", async ({ page, account: _ }) => {
  await page.goto("/help");
  await openSettingsFromSidebar(page);
  const name = page.getByLabel("Display name");
  await name.fill("Not saved yet");

  const ways: [string, () => Promise<unknown>][] = [
    ["a category", () => section(page, "Notifications").click()],
    [
      "search",
      async () => {
        await search(page).fill("password");
        await search(page).press("Enter");
      },
    ],
    ["Close", () => closeSettings(page).click()],
    ["the browser's Back", () => page.goBack()],
    ["Log out", () => page.getByRole("button", { name: "Log out" }).click()],
  ];
  for (const [way, leave] of ways) {
    const asked = answerNext(page, false);
    await leave();
    expect(await asked, way).toBe("You have unsaved changes. Leave without saving them?");
    await expect(page, way).toHaveURL("/settings/profile");
    await expect(name, way).toHaveValue("Not saved yet");
  }
  expect((await page.request.get(`${APP_URL}/api/v1/me`)).status()).toBe(200); // still signed in

  // Leave by Back: one question, then the page before Settings.
  let questions = 0;
  page.on("dialog", (dialog) => {
    questions += 1;
    void dialog.accept();
  });
  await page.goBack();
  await expect(page).toHaveURL("/help");
  expect(questions).toBe(1);
});

test("after leaving an edit behind, Back and Forward take one step each", async ({ page, account: _ }) => {
  await page.goto("/help");
  await openSettingsFromSidebar(page);
  await page.getByLabel("Display name").fill("Left behind");
  const asked = answerNext(page, true);
  await section(page, "Notifications").click();
  await asked;
  await expect(page).toHaveURL("/settings/notifications");

  await page.goBack();
  await expect(page).toHaveURL("/settings/profile");
  await expect(page.getByLabel("Display name")).not.toHaveValue("Left behind");
  await page.goBack();
  await expect(page).toHaveURL("/help");
  await page.goForward();
  await expect(page).toHaveURL("/settings/profile");
  await page.goForward();
  await expect(page).toHaveURL("/settings/notifications");
});

// ------------------------------------------------------------------ search

test("search: partial, any case, several words, nothing, typing fast; Enter and the arrow keys", async ({ page, account: _ }) => {
  await page.goto("/settings/profile");
  await waitForHydration(page);
  const links = sections(page).getByRole("link");
  const status = page.getByRole("status").filter({ hasText: /match/ });
  await expect(links).toHaveCount(SECTIONS.length);

  await search(page).fill("PASS");
  await expect(links).toHaveCount(1);
  await expect(section(page, "Privacy & Security")).toBeVisible();
  await expect(status).toHaveText("1 category match");

  await search(page).fill("dark contrast");
  await expect(links).toHaveCount(1);
  await expect(section(page, "Appearance & Accessibility")).toBeVisible();

  await search(page).fill("zzzz");
  await expect(links).toHaveCount(0);
  await expect(page.getByText("No settings match “zzzz”.")).toBeVisible();
  await expect(status).toHaveText("No settings match “zzzz”");

  await search(page).fill("");
  await search(page).pressSequentially("delete acc", { delay: 15 });
  await expect(links).toHaveCount(1);
  await expect(status).toHaveText("1 category match");
  await search(page).press("Enter");
  await expect(page).toHaveURL("/settings/privacy");
  await expect(heading(page, "Privacy & Security")).toBeFocused();
  await expect(search(page)).toHaveValue("");
  await expect(links).toHaveCount(SECTIONS.length);

  await search(page).fill("theme");
  await search(page).press("ArrowDown");
  await expect(section(page, "Appearance & Accessibility")).toBeFocused();
  await search(page).focus();
  await search(page).press("Escape");
  await expect(search(page)).toHaveValue("");
  await expect(links).toHaveCount(SECTIONS.length);
  await expectAccessible(page);
});

// ------------------------------------------------------------------ keyboard and semantics

test("keyboard only: a logical Tab order with focus always visible", async ({ page, account: _, browserName }) => {
  test.skip(browserName === "webkit", "WebKit's Tab skips links unless the user turns that on; Chromium covers the order");
  await page.goto("/settings/profile");
  await expect(heading(page, "Profile")).toBeVisible();
  await page.evaluate(() => {
    document.body.tabIndex = -1;
    document.body.focus();
    document.body.removeAttribute("tabindex");
  });
  const reached: string[] = [];
  for (let step = 0; step < 20; step += 1) {
    await page.keyboard.press("Tab");
    const focus = await describeFocus(page);
    reached.push(focus.label);
    expect(focus.onScreen, `"${focus.label}" is on screen when focused`).toBe(true);
    expect(focus.indicated, `"${focus.label}" shows a focus indicator`).toBe(true);
    if (focus.label === "Colour theme") break;
  }
  expect(reached).toEqual([
    "Skip to content",
    "Close settings",
    "INPUT",
    ...SECTIONS.map(([, name]) => name),
    "Log out",
    "Colour theme",
  ]);
  // Next: the section itself.
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest("main")))).toBe(true);
});

test("the workspace's landmarks, headings and names", async ({ page, account: _ }) => {
  await page.goto("/settings/privacy");
  await expect(heading(page, "Privacy & Security")).toBeVisible();
  await expect(page.getByRole("banner")).toMatchAriaSnapshot(`
    - banner:
      - heading "Settings" [level=1]
      - combobox "Colour theme"
  `);
  await expect(sections(page)).toMatchAriaSnapshot(`
    - navigation "Settings sections":
      - list:
        - listitem:
          - link "Profile"
        - listitem:
          - link "Academic Profile"
        - listitem:
          - link "Learning Goals"
        - listitem:
          - link "Learning Preferences"
        - listitem:
          - link "AI Tutor"
        - listitem:
          - link "Subjects & Study"
        - listitem:
          - link "Progress & Goals"
        - listitem:
          - link "Study Tracking"
        - listitem:
          - link "Learning & Streak"
        - listitem:
          - link "Notifications"
        - listitem:
          - link "Appearance & Accessibility"
        - listitem:
          - link "Privacy & Security"
        - listitem:
          - link "Help & Support"
  `);
  await expect(page.getByRole("main")).toBeVisible();
  await expect(panel(page).getByRole("button", { name: "Log out" })).toBeVisible();
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
});

// ------------------------------------------------------------------ state kept

test("a reply keeps streaming while Settings is open, and Close comes back to it", async ({ page, account: _ }) => {
  await page.goto("/");
  // Settings is opened before the reply has even begun (the new chat has no address yet).
  await page.route(
    "**/api/v1/chat/stream",
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_500));
      await route.continue();
    },
    { times: 1 },
  );
  await send(page, LONG_MESSAGE);
  await openSettingsFromSidebar(page);
  await expect(page).toHaveURL("/settings/profile");

  // Meanwhile the reply streams (about 4 s) with no chat on screen.
  await expect
    .poll(async () => (await (await page.request.get(`${APP_URL}/api/v1/conversations`)).json()).items?.length ?? 0, {
      timeout: 15_000,
    })
    .toBe(1);
  await page.waitForTimeout(6_000);

  await closeSettings(page).click();
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  await expect(lastReply(page)).toContainText("w80");
  await expect(stopButton(page)).toHaveCount(0);
  await expect(page.getByText(/didn't finish|was interrupted/)).toHaveCount(0);

  // Once it has its address, opening Settings mid-reply and coming back works the same way.
  await send(page, LONG_MESSAGE);
  await expect(stopButton(page)).toBeVisible();
  const chat = new URL(page.url()).pathname;
  await openSettingsFromSidebar(page);
  await expect(page).toHaveURL("/settings/profile");
  await closeSettings(page).click();
  await expect(page).toHaveURL(chat);
  await expect(lastReply(page)).toContainText("w80", { timeout: 15_000 });
  await expect(page.getByText(/didn't finish|was interrupted/)).toHaveCount(0);
});

test("one activity heartbeat, in the app and in Settings", async ({ page, account: _ }) => {
  const reports: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/progress/activity") reports.push(request.url());
  });
  await page.clock.install();
  await page.goto("/help");
  await page.getByRole("heading", { level: 1, name: "Help" }).click();
  await page.clock.runFor(61_000);
  await expect.poll(() => reports.length).toBe(1);

  await openSettingsFromSidebar(page);
  await expect(page).toHaveURL("/settings/profile");
  await heading(page, "Profile").click();
  await page.clock.runFor(60_000);
  await expect.poll(() => reports.length).toBe(2);
});

// ------------------------------------------------------------------ the session

test("signed out, a Settings link signs in first and then opens that section", async ({ browser, account }) => {
  const context = await browser.newContext({ baseURL: APP_URL });
  const page = await context.newPage();
  await page.goto("/settings/progress");
  await expect(page).toHaveURL("/login?redirect=%2Fsettings%2Fprogress");
  await waitForHydration(page);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/settings/progress");
  await expect(heading(page, "Progress & Goals")).toBeVisible();
  await context.close();
});

test("a session ended from another device: the next action goes to sign-in and back", async ({ page, browser, account }) => {
  await page.goto("/settings/notifications");
  await expect(heading(page, "Notifications")).toBeVisible();
  await waitForHydration(page);

  const other = await browser.newContext({ baseURL: APP_URL });
  const login = await other.request.post("/api/auth/sign-in/email", {
    data: { email: account.email, password: account.password },
    headers: SAME_ORIGIN,
  });
  expect(login.status()).toBe(200);
  expect((await other.request.post("/api/v1/auth/sessions/revoke-others", { headers: SAME_ORIGIN })).status()).toBe(204);

  await page.getByRole("switch").first().click();
  await expect(page).toHaveURL("/login?reason=expired&redirect=%2Fsettings%2Fnotifications");

  // Sign back in (the fixture deletes the account at the end).
  await waitForHydration(page);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/settings/notifications");
  await other.close();
});

test("Log out from the Settings panel does what the sidebar's does", async ({ page, account }) => {
  await page.goto("/settings/appearance");
  await expect(heading(page, "Appearance & Accessibility")).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("padhai.appearance"))).not.toBeNull();
  await panel(page).getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
  expect((await page.request.get(`${APP_URL}/api/v1/me`)).status()).toBe(401);
  expect(await page.evaluate(() => localStorage.getItem("padhai.appearance"))).toBeNull();

  // Sign back in (the fixture deletes the account at the end).
  await waitForHydration(page);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("/");
});

// ------------------------------------------------------------------ slow and failing

test("a section that can't load says so, with Try again, and the workspace keeps working", async ({ page, account: _ }) => {
  await page.route("**/api/v1/progress?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "service_unavailable", message: "down", requestId: "r" } }),
    }),
  );
  await page.goto("/settings/progress");
  await expect(page.getByRole("heading", { name: "Couldn't load your progress" })).toBeVisible();
  await section(page, "Profile").click();
  await expect(heading(page, "Profile")).toBeVisible();
  await section(page, "Progress & Goals").click();
  await expect(page.getByRole("heading", { name: "Couldn't load your progress" })).toBeVisible();
  await page.unroute("**/api/v1/progress?*");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { level: 3, name: "Today" })).toBeVisible();
});

test("on a slow network a section shows it is loading, inside the workspace", async ({ page, account: _ }) => {
  await page.goto("/settings/profile");
  await expect(heading(page, "Profile")).toBeVisible();
  await page.route(
    (url) => url.pathname === "/settings/privacy",
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2_000));
      await route.continue();
    },
  );
  await section(page, "Privacy & Security").click();
  await expect(page.locator('main [aria-busy="true"]')).toBeVisible();
  await expect(panel(page)).toBeVisible();
  await expect(heading(page, "Privacy & Security")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0);
});

// ------------------------------------------------------------------ around the breakpoint

for (const width of [767, 768, 769]) {
  test(`at ${width}px: ${width < 768 ? "the list, then one section per screen" : "the panel beside the section"}`, async ({ page, account: _ }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/settings");
    if (width < 768) {
      await expect(title(page)).toBeVisible();
      await expect(sections(page).getByRole("link")).toHaveCount(SECTIONS.length);
      await page.waitForTimeout(500);
      await expect(page).toHaveURL("/settings"); // stays on the list
      await expect(panel(page)).toHaveCount(0);
    } else {
      await expect(page).toHaveURL("/settings/profile");
      await expect(panel(page)).toBeVisible();
      await expect(page.getByRole("link", { name: "All settings" })).toHaveCount(0);
    }
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
    // Every section, reached the way a student would at this width: from the list (and back up)
    // on a phone, from the panel otherwise.
    for (const [slug, name] of SECTIONS) {
      await section(page, name).click();
      await expect(page).toHaveURL(`/settings/${slug}`);
      await expect(heading(page, name)).toBeVisible();
      await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0, { timeout: 15_000 });
      await expectNoHorizontalOverflow(page);
      await expectNoInnerOverflow(page);
      if (width < 768) {
        await page.getByRole("link", { name: "All settings" }).click();
        await expect(page).toHaveURL("/settings");
      }
    }
    await page.emulateMedia({ colorScheme: "dark" });
    await expectAccessible(page);
  });
}

test("resizing across 768px keeps you where you are", async ({ page, account: _ }) => {
  await page.setViewportSize({ width: 700, height: 900 });
  await page.goto("/settings");
  await expect(sections(page).getByRole("link")).toHaveCount(SECTIONS.length);
  await page.setViewportSize({ width: 900, height: 900 });
  await expect(page).toHaveURL("/settings/profile");
  await expect(panel(page)).toBeVisible();

  await page.goto("/settings/privacy");
  await page.setViewportSize({ width: 700, height: 900 });
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "All settings" })).toBeVisible();
  await expect(heading(page, "Privacy & Security")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("a phone on its side (844×390): the panel scrolls, everything is reachable", async ({ page, account: _ }) => {
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto("/settings/profile");
  await expect(panel(page)).toBeVisible();
  await expect(closeSettings(page)).toBeVisible();
  await section(page, "Help & Support").scrollIntoViewIfNeeded();
  await section(page, "Help & Support").click();
  await expect(heading(page, "Help & Support")).toBeVisible();
  await expect(panel(page).getByRole("button", { name: "Log out" })).toBeInViewport({ ratio: 1 });
  await expectNoHorizontalOverflow(page);
  await expectNoInnerOverflow(page);
  await expectAccessible(page);
});
