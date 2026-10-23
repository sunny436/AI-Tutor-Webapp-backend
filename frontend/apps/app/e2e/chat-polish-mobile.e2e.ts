import type { Page } from "@playwright/test";

import {
  composer,
  emptyGreeting,
  expect,
  expectNoHorizontalOverflow,
  expectStudyGreeting,
  renameChat,
  seedTurn,
  sendAndWait,
  test,
  waitForHydration,
} from "./support";

/**
 * The chat's polish on a phone (Pixel 7, touch): the greeting, the header's name, the composer
 * and the drawer's chat list at the phone widths that matter, upright and sideways. Emulated: a
 * real device's keyboard and browser chrome are checked by hand (docs/deployment.md list).
 */

const SIZES = [
  { width: 430, height: 932 },
  { width: 390, height: 844 },
  { width: 375, height: 667 },
  { width: 360, height: 740 },
  { width: 844, height: 390 }, // sideways
];

async function expectInside(page: Page, width: number, height: number) {
  for (const [name, locator] of [
    ["greeting", emptyGreeting(page)],
    ["header", page.getByRole("banner").getByRole("heading", { level: 1 })],
    ["composer", composer(page)],
  ] as const) {
    const box = await locator.boundingBox();
    expect(box, name).not.toBeNull();
    if (!box) continue;
    expect(box.x, `${name} left`).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width, `${name} right`).toBeLessThanOrEqual(width + 0.5);
    expect(box.y + box.height, `${name} bottom`).toBeLessThanOrEqual(height + 0.5);
  }
}

test("phones, upright and sideways: greeting, name, composer and the drawer's long titles fit", async ({
  page,
  account: _,
}) => {
  test.setTimeout(120_000);
  const LONG = "A very long chat title about photosynthesis, respiration and the carbon cycle in green plants";
  const long = await seedTurn(page, "Explain photosynthesis");
  await renameChat(page, long, LONG);

  for (const { width, height } of SIZES) {
    await test.step(`${width}×${height}`, async () => {
      await page.setViewportSize({ width, height });
      await page.goto("/");
      await waitForHydration(page);
      await expectStudyGreeting(page);
      await expect(page.getByRole("banner").getByRole("heading", { level: 1 })).toHaveText("New chat");
      await expectInside(page, width, height);
      await expectNoHorizontalOverflow(page);

      // The drawer below `md`; sideways a phone is wide enough for the rail.
      const drawer = width < 768;
      if (drawer) await page.getByRole("button", { name: "Open menu" }).click();
      const panel = drawer ? page.getByRole("dialog", { name: "Navigation" }) : page.getByRole("complementary");
      await expect(panel.getByRole("navigation", { name: "Learning Hub" })).toHaveCount(0);
      const row = panel.locator(`a[href='/c/${long}']`);
      await expect(row).toHaveAccessibleName(LONG);
      expect(await row.locator(".marquee").evaluate((box) => box.scrollWidth > box.clientWidth)).toBe(true);
      // Touch has no hover: a long title sits still (an ellipsis) until the chat is opened.
      expect(await row.locator(".marquee-track").evaluate((track) => track.getAnimations().length)).toBe(0);
      const rowBox = await row.boundingBox();
      const panelBox = await panel.boundingBox();
      expect((rowBox?.x ?? 0) + (rowBox?.width ?? 0)).toBeLessThanOrEqual((panelBox?.x ?? 0) + (panelBox?.width ?? 0) + 0.5);
      await expectNoHorizontalOverflow(page);
      if (drawer) await page.keyboard.press("Escape");
    });
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await waitForHydration(page);
  await sendAndWait(page, "What is osmosis?");
  await expect(page.getByRole("banner").getByRole("heading", { level: 1 })).toHaveText("Osmosis Explained");
  await expectNoHorizontalOverflow(page);
});
