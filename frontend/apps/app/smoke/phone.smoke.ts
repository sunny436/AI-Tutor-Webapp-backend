import { expect, test } from "@playwright/test";

import {
  GREETING_SHAPE,
  badge,
  bell,
  checklist,
  closeCelebrations,
  forceDark,
  hydrated,
  legacyColours,
  noActivityReports,
  renderedGreetingContrast,
  shot,
  sideways,
} from "./support";

/**
 * A phone, emulated (iPhone 14 in WebKit; Pixel 7 in Chrome). Read-only: nothing is sent or saved.
 * Real devices remain a manual check: emulation gets the engine, the size and touch, not the
 * device's keyboard, notch or browser chrome.
 */
test("phone: the new chat, the drawer, a chat and Settings fit, light and dark", async ({ page }, info) => {
  const device = info.project.name;
  const { check, finish } = checklist(`PRODUCTION SMOKE: ${device}`);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await noActivityReports(page);
  await closeCelebrations(page);
  await page.goto("/");
  await hydrated(page);

  await check("new chat: the greeting and the composer are on screen; the header fits; no sideways scroll", async () => {
    const title = page.getByRole("main").getByRole("heading", { level: 2 });
    await expect(title).toHaveText(GREETING_SHAPE);
    await expect(page.getByRole("textbox", { name: "Ask your doubt" })).toBeInViewport();
    await expect(title).toBeInViewport();
    await expect(badge(page)).toBeVisible();
    await expect(bell(page)).toBeVisible();
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `${device}-home-light`);
    // textContent: WebKit's innerText drops the space where the line wraps.
    return `"${(await title.textContent())?.replace(/\s+/g, " ").trim()}"`;
  });

  await check("greeting as rendered, light and dark: 4.5:1 or better at every point; no violet", async () => {
    const light = await renderedGreetingContrast(page);
    expect(light).toBeGreaterThanOrEqual(4.5);
    await forceDark(page);
    const dark = await renderedGreetingContrast(page);
    expect(dark).toBeGreaterThanOrEqual(4.5);
    expect(await legacyColours(page)).toEqual([]);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `${device}-home-dark`);
    return `lowest ${light.toFixed(2)}:1 light, ${dark.toFixed(2)}:1 dark`;
  });

  await check("drawer: opens with the chats, titles at rest (no slide on touch), closes", async () => {
    await page.goto("/");
    await hydrated(page);
    await page.getByRole("button", { name: "Open menu" }).click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("link", { name: "Ask New Doubt" })).toBeVisible();
    await page.waitForTimeout(800);
    const running = await drawer.locator(".marquee-track").evaluateAll((tracks) => tracks.map((track) => track.getAnimations().length));
    expect(running.every((count) => count === 0)).toBe(true);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `${device}-drawer-light`);
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    return `${running.length} chats in the drawer`;
  });

  await check("an existing chat: the reply shows and fits, light and dark", async () => {
    const chats = await (await page.request.get("/api/v1/conversations")).json();
    const id = chats.items?.[0]?.id;
    if (!id) return "no chats on this account to open";
    await page.goto(`/c/${id}`);
    await hydrated(page);
    await expect(page.getByRole("article", { name: "Assistant" }).first()).toBeVisible();
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await forceDark(page);
    expect(await legacyColours(page)).toEqual([]);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `${device}-chat-dark`);
  });

  await check("Settings: sections open and fit, light and dark", async () => {
    for (const path of ["/settings/profile", "/settings/streak", "/settings/notifications"]) {
      await page.goto(path);
      await hydrated(page);
      await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
      expect(await sideways(page), `${path} light`).toBeLessThanOrEqual(0);
      await forceDark(page);
      expect(await sideways(page), `${path} dark`).toBeLessThanOrEqual(0);
      expect(await legacyColours(page), path).toEqual([]);
    }
    await shot(page, `${device}-settings-dark`, true);
  });

  await check("no uncaught errors in the page", async () => {
    expect(errors).toEqual([]);
  });

  finish();
});
