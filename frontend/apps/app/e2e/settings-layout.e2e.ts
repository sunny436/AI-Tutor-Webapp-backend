import { expect, expectNoHorizontalOverflow, test } from "./support";

/**
 * Settings as product cards: every section at every width fits (no sideways scroll, no card wider
 * than itself), and the cards turn horizontal where there is room: a field is a row (label |
 * control) on wide screens and stacks on phones.
 */

const WIDTHS = [320, 375, 768, 1024, 1280, 1440];
// Every section (src/features/settings/sections.ts), including the calendar, sessions and topic chips.
const SECTIONS = ["profile", "academic", "goals", "learning", "tutor", "subjects", "progress", "study-tracking", "streak", "notifications", "appearance", "privacy", "help"];

test("every Settings section fits at 320 to 1440px, cards included", async ({ page, account: _ }) => {
  test.setTimeout(6 * 60_000);
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    for (const slug of SECTIONS) {
      await page.goto(`/settings/${slug}`);
      await expect(page.getByRole("main").getByRole("heading", { level: 2 }).first()).toBeVisible();
      await expectNoHorizontalOverflow(page);
      const overflowing = await page
        .getByRole("main")
        .locator(".elev-1")
        .evaluateAll((cards) => cards.filter((card) => card.scrollWidth > card.clientWidth + 1).length);
      expect(overflowing, `${slug} at ${width}px`).toBe(0);
    }
  }
});

test("a field is a row on wide screens and stacks on phones; choice groups keep their names", async ({ page, account: _ }) => {
  const positions = async () => {
    const label = await page.getByText("Display name", { exact: true }).boundingBox();
    const input = await page.getByLabel("Display name").boundingBox();
    return { label, input };
  };

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/settings/profile");
  let { label, input } = await positions();
  expect(label && input && label.x + label.width <= input.x).toBe(true); // side by side

  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/settings/profile");
  ({ label, input } = await positions());
  expect(label && input && label.y + label.height <= input.y).toBe(true); // stacked

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/settings/learning");
  const group = page.getByRole("group", { name: "Reply language" });
  await expect(group.getByRole("radio")).not.toHaveCount(0);
});
