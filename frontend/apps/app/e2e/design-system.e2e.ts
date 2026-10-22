import type { Page } from "@playwright/test";

import {
  expect,
  expectAccessible,
  expectNoHorizontalOverflow,
  renameChat,
  seedTurn,
  sendAndWait,
  test,
  waitForHydration,
} from "./support";

/**
 * The design system as it renders, across the whole app: no colour of the retired indigo/violet
 * palette on screen (computed styles, not a grep: text, fills, borders, outlines, shadows,
 * gradients, SVG), every page accessible with high contrast on, and titles in any script held
 * inside the sidebar and the header.
 */

/** Visible elements painting a violet-family colour (hue 245-300, saturated, not near-grey). */
function legacyColours(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const colours = (value: string): number[][] =>
      [...value.matchAll(/rgba?\(([^)]+)\)|color\(srgb ([^)]+)\)/g)].map((match) => {
        if (match[1]) {
          const [r = 0, g = 0, b = 0, a = 1] = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
          return [r, g, b, a];
        }
        const [r = 0, g = 0, b = 0, a = 1] = (match[2] ?? "").split(/[\s/]+/).filter(Boolean).map(Number);
        return [r * 255, g * 255, b * 255, a];
      });
    const hsl = (r: number, g: number, b: number) => {
      const [x, y, z] = [r / 255, g / 255, b / 255];
      const max = Math.max(x, y, z);
      const min = Math.min(x, y, z);
      const l = (max + min) / 2;
      const d = max - min;
      if (!d) return [0, 0, l * 100];
      const s = d / (1 - Math.abs(2 * l - 1));
      let h = max === x ? ((y - z) / d) % 6 : max === y ? (z - x) / d + 2 : (x - y) / d + 4;
      h = (h * 60 + 360) % 360;
      return [h, s * 100, l * 100];
    };
    const found = new Set<string>();
    for (const element of document.querySelectorAll<Element>("body *")) {
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) continue;
      const style = getComputedStyle(element);
      if (style.visibility === "hidden" || Number(style.opacity) === 0) continue;
      const painted = [
        style.color,
        style.backgroundColor,
        style.backgroundImage,
        style.boxShadow,
        style.fill,
        style.stroke,
        style.outlineStyle !== "none" ? style.outlineColor : "",
        Number.parseFloat(style.borderTopWidth) ? style.borderTopColor : "",
        Number.parseFloat(style.borderBottomWidth) ? style.borderBottomColor : "",
        Number.parseFloat(style.borderLeftWidth) ? style.borderLeftColor : "",
        Number.parseFloat(style.borderRightWidth) ? style.borderRightColor : "",
      ];
      for (const value of painted) {
        for (const [r = 0, g = 0, b = 0, a = 1] of colours(value)) {
          const [h = 0, s = 0, l = 0] = hsl(r, g, b);
          if (a > 0.1 && s > 20 && l > 12 && l < 92 && h >= 245 && h <= 300) {
            found.add(`${element.tagName.toLowerCase()}.${String(element.getAttribute("class") ?? "").slice(0, 60)} → ${value.slice(0, 80)}`);
          }
        }
      }
    }
    return [...found].slice(0, 20);
  });
}

test("no indigo or violet left anywhere on screen, light and dark", async ({ page, browser, account: _ }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await waitForHydration(page);
  await sendAndWait(page, "A **table**:\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n```ts\nconst x = 1;\n```\n\n$e^{i\\pi} + 1 = 0$ and [a link](https://example.com)");
  const chat = new URL(page.url()).pathname;
  const signedOut = await browser.newPage();
  for (const scheme of ["light", "dark"] as const) {
    for (const path of ["/", chat, "/learning", "/settings/profile", "/settings/progress", "/settings/appearance", "/settings/streak", "/no-such-page"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await legacyColours(page), `${path} (${scheme})`).toEqual([]);
    }
    // A menu and a dialog open.
    await page.goto("/");
    await waitForHydration(page);
    await page.getByRole("complementary").getByRole("button", { name: /^Account: / }).click();
    await expect(page.getByRole("menu")).toBeVisible();
    expect(await legacyColours(page), `account menu (${scheme})`).toEqual([]);
    await page.keyboard.press("Escape");
    await page.getByRole("complementary").getByRole("button", { name: /^Rename/ }).first().click();
    await expect(page.getByRole("dialog", { name: "Rename chat" })).toBeVisible();
    expect(await legacyColours(page), `rename dialog (${scheme})`).toEqual([]);
    await page.keyboard.press("Escape");
    await signedOut.emulateMedia({ colorScheme: scheme });
    for (const path of ["/login", "/signup"]) {
      await signedOut.goto(path);
      await signedOut.waitForLoadState("networkidle");
      expect(await legacyColours(signedOut), `${path} signed out (${scheme})`).toEqual([]);
    }
  }
  await signedOut.close();
});

test("with high contrast on, the chat and Settings stay accessible, light and dark", async ({ page, account: _ }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const path of ["/", "/learning", "/settings/profile", "/settings/learning"]) {
      await page.goto(path);
      await waitForHydration(page);
      await page.evaluate(() => document.documentElement.setAttribute("data-contrast", "high"));
      await expectAccessible(page);
    }
  }
});

test("titles in any script, and very long ones, stay inside the sidebar and the header", async ({ page, account: _ }) => {
  test.setTimeout(90_000);
  const titles = [
    "प्रकाश संश्लेषण क्या होता है और यह पौधों के लिए क्यों ज़रूरी है",
    "Newton ke teesre niyam ka matlab kya hai bhai zara samjhao",
    "Pneumonoultramicroscopicsilicovolcanoconiosisandmanymorelettersinoneverylongword",
  ];
  const ids: string[] = [];
  for (const [index, title] of titles.entries()) {
    const id = await seedTurn(page, `Question number ${index} about science`);
    await renameChat(page, id, title);
    ids.push(id);
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 800 });
    for (const [index, id] of ids.entries()) {
      await page.goto(`/c/${id}`);
      await waitForHydration(page);
      const heading = page.getByRole("banner").getByRole("heading", { level: 1 });
      await expect(heading).toHaveText(titles[index] ?? "");
      const box = await heading.boundingBox();
      expect((box?.x ?? 0) + (box?.width ?? 0), `the header's title fits at ${width}px`).toBeLessThanOrEqual(width + 0.5);
      await expectNoHorizontalOverflow(page);
    }
    const drawer = width < 768;
    if (drawer) await page.getByRole("button", { name: "Open menu" }).click();
    const panel = drawer ? page.getByRole("dialog", { name: "Navigation" }) : page.getByRole("complementary");
    // The drawer slides in: measure it where it lands, not on the way.
    await panel.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
    const panelBox = await panel.boundingBox();
    for (const [index, id] of ids.entries()) {
      const row = panel.locator(`a[href='/c/${id}']`);
      await expect(row).toHaveAccessibleName(titles[index] ?? "");
      const rowBox = await row.boundingBox();
      expect((rowBox?.x ?? 0) + (rowBox?.width ?? 0)).toBeLessThanOrEqual((panelBox?.x ?? 0) + (panelBox?.width ?? 0) + 0.5);
    }
    await expectNoHorizontalOverflow(page);
    if (drawer) await page.keyboard.press("Escape");
  }
});

test("every text field's edge clears 3:1 against what is behind it, light and dark", async ({ page, browser, account: _ }) => {
  const edges = (target: Page) =>
    target.evaluate(() => {
      const luminance = (value: string) =>
        (value.match(/[\d.]+/g) ?? [])
          .slice(0, 3)
          .map(Number)
          .map((v) => v / 255)
          .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
          .reduce((sum, c, index) => sum + c * ([0.2126, 0.7152, 0.0722][index] ?? 0), 0);
      const behind = (element: Element) => {
        for (let node = element.parentElement; node; node = node.parentElement) {
          const colour = getComputedStyle(node).backgroundColor;
          if (!/rgba\(.*, 0\)$/.test(colour) && colour !== "transparent") return colour;
        }
        return getComputedStyle(document.body).backgroundColor;
      };
      return [...document.querySelectorAll<HTMLElement>("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea")]
        .filter((field) => field.getBoundingClientRect().width > 0 && getComputedStyle(field).borderTopWidth !== "0px")
        .map((field) => {
          const [a, b] = [luminance(getComputedStyle(field).borderTopColor), luminance(behind(field))];
          return { name: field.getAttribute("aria-label") ?? field.id ?? field.tagName, ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
        });
    });
  const signedOut = await browser.newPage();
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await signedOut.emulateMedia({ colorScheme: scheme });
    for (const [target, path] of [
      [page, "/settings/profile"],
      [page, "/settings/privacy"],
      [signedOut, "/login"],
    ] as const) {
      await target.goto(path);
      await target.waitForLoadState("networkidle");
      const found = await edges(target);
      expect(found.length, `fields on ${path}`).toBeGreaterThan(0);
      for (const field of found) expect(field.ratio, `${field.name} on ${path} (${scheme})`).toBeGreaterThanOrEqual(3);
    }
  }
  await signedOut.close();
});
