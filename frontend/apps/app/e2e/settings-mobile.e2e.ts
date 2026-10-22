/**
 * Settings on a phone: the list of sections, one section per screen, "All settings" and the
 * browser's Back to go up (the list comes back where it was, with focus on the row just left),
 * and Close to leave. Runs on a Chromium phone and a WebKit phone (playwright.config.ts).
 */

import { type Page, expect } from "@playwright/test";

import { expectAccessible, expectNoHorizontalOverflow, lastReply, openSettingsFromSidebar, seedTurn, test } from "./support";

const rows = (page: Page) => page.getByRole("navigation", { name: "Settings sections" }).getByRole("link");
const row = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name, exact: true });
const heading = (page: Page, name: string) => page.getByRole("heading", { level: 2, name, exact: true });
const up = (page: Page) => page.getByRole("link", { name: "All settings" });
const listScroll = (page: Page) => page.locator("main").evaluate((main) => main.scrollTop);

test("on a phone: the list, a section, back up to the same place, and out", async ({ page, account: _ }) => {
  await page.setViewportSize({ width: page.viewportSize()?.width ?? 390, height: 640 });
  const id = await seedTurn(page, "A chat on a phone");
  await page.goto(`/c/${id}`);
  await expect(lastReply(page)).toBeVisible();

  await page.getByRole("button", { name: "Open menu" }).click();
  await openSettingsFromSidebar(page, page.getByRole("dialog", { name: "Navigation" }));
  await expect(page).toHaveURL("/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeFocused();
  await expect(rows(page)).toHaveCount(13); // every section (src/features/settings/sections.ts)
  await expect(page.getByRole("navigation", { name: "Learning Hub" })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await expectAccessible(page);

  // The last row is below the fold: scroll to it and open it.
  await row(page, "Help & Support").scrollIntoViewIfNeeded();
  const scrolled = await listScroll(page);
  expect(scrolled).toBeGreaterThan(0);
  await row(page, "Help & Support").click();
  await expect(page).toHaveURL("/settings/help");
  await expect(heading(page, "Help & Support")).toBeFocused();
  await expect(rows(page)).toHaveCount(0);
  await expectAccessible(page);

  // Up: the list, where it was, focus on the row just left.
  await up(page).click();
  await expect(page).toHaveURL("/settings");
  await expect(row(page, "Help & Support")).toBeFocused();
  expect(Math.abs((await listScroll(page)) - scrolled)).toBeLessThanOrEqual(2);

  // The browser's Back does the same.
  await row(page, "Help & Support").click();
  await expect(heading(page, "Help & Support")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL("/settings");
  await expect(row(page, "Help & Support")).toBeFocused();
  expect(Math.abs((await listScroll(page)) - scrolled)).toBeLessThanOrEqual(2);

  await page.getByRole("link", { name: "Close settings" }).click();
  await expect(page).toHaveURL(`/c/${id}`);
  await expect(lastReply(page)).toBeVisible();
});

test("on a phone: an unsaved edit is asked about on All settings, Back and Close", async ({ page, account: _ }) => {
  await page.goto("/settings");
  await row(page, "Profile").click();
  const name = page.getByLabel("Display name");
  await name.fill("Typed on a phone");
  for (const leave of [() => up(page).click(), () => page.goBack(), () => page.getByRole("link", { name: "Close settings" }).click()]) {
    page.once("dialog", (dialog) => void dialog.dismiss());
    await leave();
    await expect(page).toHaveURL("/settings/profile");
    await expect(name).toHaveValue("Typed on a phone");
  }
  page.once("dialog", (dialog) => void dialog.accept());
  await up(page).click();
  await expect(page).toHaveURL("/settings");
  await expectNoHorizontalOverflow(page);
});
