import { expect, expectAccessible, lastReply, sendAndWait, test } from "./support";

test("sign-in and sign-up pages", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expectAccessible(page);
  await page.goto("/signup");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await expectAccessible(page);
});

test("the chat, empty and with a reply, in light and dark", async ({ page, account: _ }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "How can I help?" })).toBeVisible();
  await expectAccessible(page);

  await sendAndWait(page, "A **table**:\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n```ts\nconst x = 1;\n```\n\n$e^{i\\pi} + 1 = 0$");
  await expect(lastReply(page).getByRole("table")).toBeVisible();
  await expectAccessible(page);

  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
});

test("settings, and the delete-account dialog", async ({ page, account: _ }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expectAccessible(page);
  await page.getByRole("button", { name: "Delete account" }).click();
  await expect(page.getByRole("dialog", { name: "Delete your account?" })).toBeVisible();
  await expectAccessible(page);
});

test("the skip link goes to the page, then one Tab reaches the message box", async ({ page, account: _ }) => {
  await page.goto("/");
  // Arrival focuses the composer on a desktop. Start from the top, as a fresh
  // visit does: focusing <body> moves the browser's Tab starting point there.
  await page.evaluate(() => {
    document.body.tabIndex = -1;
    document.body.focus();
    document.body.removeAttribute("tabindex");
  });
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: /skip to/i });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
});
