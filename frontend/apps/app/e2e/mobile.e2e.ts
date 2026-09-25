import { composer, expect, expectAccessible, lastReply, sendAndWait, test } from "./support";

const WIDE = [
  "A wide table and a long line of code:",
  "",
  "| Column one | Column two | Column three | Column four | Column five | Column six | Column seven |",
  "| --- | --- | --- | --- | --- | --- | --- |",
  "| a fairly long cell | another long cell | more text here | and more | and more | and more | the end |",
  "",
  "```js",
  `const veryLongLine = "${"x".repeat(200)}";`,
  "```",
].join("\n");

test("on a phone: the drawer, the composer, and no sideways scrolling", async ({ page, account: _ }) => {
  await page.goto("/");
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("no viewport");

  await test.step("the composer sits inside the screen", async () => {
    const box = await composer(page).boundingBox();
    expect(box).not.toBeNull();
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(viewport.height);
  });

  await test.step("wide tables and long code scroll inside the reply, not the page", async () => {
    await sendAndWait(page, WIDE);
    await expect(lastReply(page).getByRole("table")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await expectAccessible(page);
  });

  await test.step("the menu opens as a dialog, closes with Escape, and gives focus back", async () => {
    const open = page.getByRole("button", { name: "Open menu" });
    await open.click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await expect(drawer).toBeVisible();
    // (Outside the open modal everything is aria-hidden, so find it by selector.)
    await expect(page.locator("button[aria-label='Open menu']")).toHaveAttribute("aria-expanded", "true");
    await expect(drawer.getByRole("link", { name: "Ask New Doubt" })).toBeVisible();
    await expectAccessible(page);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(open).toBeFocused();
  });

  await test.step("choosing from the drawer navigates and closes it", async () => {
    const conversation = new URL(page.url()).pathname;
    await page.getByRole("button", { name: "Open menu" }).click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await drawer.getByRole("link", { name: "Ask New Doubt" }).click();
    await expect(drawer).toBeHidden();
    await expect(page).toHaveURL("/");

    await page.getByRole("button", { name: "Open menu" }).click();
    await drawer.locator(`a[href="${conversation}"]`).click();
    await expect(drawer).toBeHidden();
    await expect(page).toHaveURL(conversation);
    await expect(lastReply(page).getByRole("table")).toBeVisible();
  });
});
