import {
  composer,
  describeFocus,
  emptyGreeting,
  expect,
  expectAccessible,
  expectStudyGreeting,
  lastReply,
  seedTurn,
  sendAndWait,
  test,
  waitForHydration,
} from "./support";

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
  await expectStudyGreeting(page);
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
  await expect(composer(page)).toBeFocused();
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
  for (const name of ["Ask New Doubt"]) {
    const control = page.getByRole("complementary").getByRole("link", { name });
    await control.focus();
    // (Filtered: the previous tooltip can still be fading out.)
    await expect(page.getByRole("tooltip").filter({ hasText: name })).toHaveCount(1);
  }
  // The account (Settings and Log out are in its menu): named on focus too.
  const account = page.getByRole("complementary").getByRole("button", { name: /^Account: / });
  await account.focus();
  const who = ((await account.getAttribute("aria-label")) ?? "").replace(/^Account: /, "");
  await expect(page.getByRole("tooltip").filter({ hasText: who })).toHaveCount(1);
  await expectAccessible(page);
});

test("the chat dialogs keep focus inside, close on Escape and give focus back", async ({ page, account: _ }) => {
  const id = await seedTurn(page, "A chat to open dialogs on");
  await page.goto("/");
  // Before hydration the composer's autofocus would take focus back from the button below.
  await waitForHydration(page);
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

test("the skip link goes to the page, then Tab reaches the message box", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  // Arrival focuses the composer on a desktop (once hydrated; wait for it, or it
  // takes focus back after the reset below). Then start from the top, as a fresh
  // visit does: focusing <body> moves the browser's Tab starting point there.
  await expect(composer(page)).toBeFocused();
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
  // A new chat is its greeting and the message box: only Attach files comes before it.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Attach files" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(composer(page)).toBeFocused();
});
