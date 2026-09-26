import { describeFocus, expect, expectAccessible, lastReply, seedTurn, sendAndWait, test } from "./support";

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
  await expect(page.getByRole("heading", { name: "How can I help your studies today?" })).toBeVisible();
  await expectAccessible(page);

  await sendAndWait(page, "A **table**:\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n```ts\nconst x = 1;\n```\n\n$e^{i\\pi} + 1 = 0$");
  await expect(lastReply(page).getByRole("table")).toBeVisible();
  await expectAccessible(page);

  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
});

test("settings, and the delete-account dialog", async ({ page, account: _ }) => {
  await page.goto("/settings/privacy");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expectAccessible(page);
  const trigger = page.getByRole("button", { name: "Delete account" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Delete your account?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Password")).toBeFocused();
  await expectAccessible(page);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("every control reached by Tab shows where focus is", async ({ page, account: _ }) => {
  await seedTurn(page, "A chat, so the list has rows and row actions");
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
  await page.evaluate(() => {
    document.body.tabIndex = -1;
    document.body.focus();
    document.body.removeAttribute("tabindex");
  });
  const reached: string[] = [];
  for (let step = 0; step < 40; step += 1) {
    await page.keyboard.press("Tab");
    const focus = await describeFocus(page);
    reached.push(focus.label);
    expect(focus.onScreen, `"${focus.label}" is on screen when focused`).toBe(true);
    expect(focus.indicated, `"${focus.label}" shows a focus indicator`).toBe(true);
    if (focus.isComposer) break;
  }
  expect(reached.length, `Tab reached the message box: ${reached.join(" → ")}`).toBeLessThan(40);
});

test("the collapsed rail names its controls on keyboard focus", async ({ page, account: _ }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  for (const name of ["Ask New Doubt", "AI Tutor", "Settings", "Log out"]) {
    const control = page.getByRole("complementary").getByRole(name === "Log out" ? "button" : "link", { name });
    await control.focus();
    // (Filtered: the previous tooltip can still be fading out.)
    await expect(page.getByRole("tooltip").filter({ hasText: name })).toHaveCount(1);
  }
  await expectAccessible(page);
});

test("the chat dialogs keep focus inside, close on Escape and give focus back", async ({ page, account: _ }) => {
  const id = await seedTurn(page, "A chat to open dialogs on");
  await page.goto("/");
  const item = page.locator("li", { has: page.locator(`a[href="/c/${id}"]`) });
  const staysInside = async (name: string) => {
    for (let step = 0; step < 6; step += 1) {
      await page.keyboard.press("Tab");
      const inside = await page
        .getByRole("dialog", { name })
        .evaluate((dialog) => dialog.contains(document.activeElement));
      expect(inside, `focus stays inside "${name}"`).toBe(true);
    }
  };

  await test.step("rename: focus starts in the field", async () => {
    const trigger = item.getByRole("button", { name: /^Rename/ });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Rename chat" });
    await expect(dialog.getByLabel("Name")).toBeFocused();
    await expectAccessible(page);
    await staysInside("Rename chat");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  await test.step("delete: focus starts on Cancel, never on the destructive button", async () => {
    const trigger = item.getByRole("button", { name: /^Delete/ });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Delete this chat?" });
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
    await expectAccessible(page);
    await staysInside("Delete this chat?");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(page.locator(`nav a[href="/c/${id}"]`)).toBeVisible();
  });
});

test("the skip link goes to the page, then Tab reaches the suggestions and the message box", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  // Arrival focuses the composer on a desktop (once hydrated; wait for it, or it
  // takes focus back after the reset below). Then start from the top, as a fresh
  // visit does: focusing <body> moves the browser's Tab starting point there.
  await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
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
  // A new chat offers four suggested questions first, in reading order, then the box.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /^Explain Photosynthesis/ })).toBeFocused();
  for (let step = 0; step < 3; step += 1) await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /^French Revolution Recapped/ })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
});
