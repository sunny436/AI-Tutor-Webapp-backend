import { APP_URL } from "./env";
import {
  PASSWORD,
  SAME_ORIGIN,
  chatLinks,
  composer,
  createAccount,
  deleteAccount,
  expect,
  lastReply,
  replies,
  seedTurn,
  send,
  test,
  waitForIdle,
} from "./support";

/**
 * The workflows the journey does not walk through. Written against the names and
 * behaviour the UI already has, so a restyle that breaks any of them fails here.
 */

test("the chat list: first page, load more, search and no match", async ({ page, account: _ }) => {
  test.setTimeout(120_000);
  // One more than the sidebar's page (PAGE_SIZE = 30), oldest first.
  for (let index = 1; index <= 31; index += 1) {
    await seedTurn(page, `Seeded chat number ${String(index).padStart(2, "0")}`);
  }

  await page.goto("/");
  await expect(chatLinks(page)).toHaveCount(30);
  // Newest activity first: the last one seeded heads the list, the first is on page two. (Each is
  // named after its question, in title case: app/chat/titles.py.)
  await expect(chatLinks(page).first()).toHaveText("Seeded Chat Number 31");
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(chatLinks(page)).toHaveCount(31);
  await expect(chatLinks(page).last()).toHaveText("Seeded Chat Number 01");
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);

  const search = page.getByRole("textbox", { name: "Search chats" });
  await search.fill("number 07");
  await expect(chatLinks(page)).toHaveCount(1);
  await expect(chatLinks(page)).toHaveText("Seeded Chat Number 07");
  await search.fill("nothing like this");
  await expect(chatLinks(page)).toHaveCount(0);
  await expect(page.getByText("No chat matches that.")).toBeVisible();
  await search.fill("");
  await expect(chatLinks(page)).toHaveCount(31);
});

test("a long conversation loads its earlier messages on request", async ({ page, account: _ }) => {
  test.setTimeout(120_000);
  // 26 turns = 52 messages; the chat loads the latest 50.
  const id = await seedTurn(page, "Turn 01");
  for (let index = 2; index <= 26; index += 1) {
    await seedTurn(page, `Turn ${String(index).padStart(2, "0")}`, id);
  }

  await page.goto(`/c/${id}`);
  await expect(page.getByRole("article")).toHaveCount(50);
  await expect(page.getByRole("article", { name: "You" }).first()).toContainText("Turn 02");
  await page.getByRole("button", { name: "Load earlier messages" }).click();
  await expect(page.getByRole("article")).toHaveCount(52);
  await expect(page.getByRole("article", { name: "You" }).first()).toContainText("Turn 01");
  await expect(page.getByRole("button", { name: "Load earlier messages" })).toHaveCount(0);
});

test("the sidebar collapses to a rail, and stays that way after a reload", async ({ page, account: _ }) => {
  await seedTurn(page, "Something in the list");
  await page.goto("/");
  await expect(chatLinks(page)).toHaveCount(1);

  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
  await expect(chatLinks(page)).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
  await expect(chatLinks(page)).toHaveCount(0);

  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await expect(chatLinks(page)).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole("button", { name: "Collapse sidebar" })).toBeVisible();
  await expect(chatLinks(page)).toHaveCount(1);
});

test("the colour theme can be switched, and the choice is remembered", async ({ page, account: _ }) => {
  await page.goto("/settings/appearance");
  const html = page.locator("html");

  await page.getByRole("main").getByRole("radio", { name: "Dark" }).check();
  await expect(html).toHaveClass(/\bdark\b/);
  await expect.poll(async () => (await (await page.request.get("/api/v1/me/appearance")).json()).theme).toBe("dark");
  await page.reload();
  await expect(html).toHaveClass(/\bdark\b/);

  // The quick switch in the Settings top bar (the app header's theme menu shares it) saves to the account too.
  await page.getByRole("banner").getByRole("combobox", { name: "Colour theme" }).click();
  await page.getByRole("option", { name: "Light" }).click();
  await expect(html).not.toHaveClass(/\bdark\b/);
  await expect.poll(async () => (await (await page.request.get("/api/v1/me/appearance")).json()).theme).toBe("light");
  await page.reload();
  await expect(html).not.toHaveClass(/\bdark\b/);
  await expect(page.getByRole("main").getByRole("radio", { name: "Light" })).toBeChecked();
});

test("changing the password: a wrong current one is refused, the new one signs in", async ({ page }) => {
  const { email } = await createAccount(page, "password");
  const next = `${PASSWORD}-changed`;
  try {
    await page.goto("/settings/privacy");
    await page.getByLabel("Current password").fill("not-the-password");
    await page.getByLabel("New password", { exact: true }).fill(next);
    await page.getByLabel("Confirm new password").fill(next);
    await page.getByRole("button", { name: "Change password", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Your current password isn't right." })).toBeVisible();

    await page.getByLabel("Current password").fill(PASSWORD);
    await page.getByLabel("New password", { exact: true }).fill(next);
    await page.getByLabel("Confirm new password").fill(next);
    await page.getByRole("button", { name: "Change password", exact: true }).click();
    await expect(page.getByText("Password changed. Your other devices have been signed out.")).toBeVisible();

    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    // The old password no longer works. (Scoped to the form: Next's route announcer is a role="alert" too.)
    await expect(page.locator("form").getByRole("alert")).toBeVisible();
    await page.getByLabel("Password", { exact: true }).fill(next);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL("/");
    await expect(composer(page)).toBeVisible();
  } finally {
    await deleteAccount(page, next);
  }
});

test("signing out other devices ends their sessions, not this one", async ({ page, browser, account }) => {
  const other = await browser.newContext({ baseURL: APP_URL });
  try {
    const login = await other.request.post("/api/auth/sign-in/email", {
      data: { email: account.email, password: account.password },
      headers: SAME_ORIGIN,
    });
    expect(login.status()).toBe(200);
    expect((await other.request.get("/api/v1/me")).status()).toBe(200);

    await page.goto("/settings/privacy");
    await page.getByRole("button", { name: "Sign out other devices" }).click();
    await expect(page.getByText("Signed out of all other devices.")).toBeVisible();

    expect((await other.request.get("/api/v1/me")).status()).toBe(401);
    expect((await page.request.get("/api/v1/me")).status()).toBe(200);
  } finally {
    await other.close();
  }
});

test("cancelling a rename or a delete changes nothing", async ({ page, account: _ }) => {
  const id = await seedTurn(page, "Keep this chat");
  await page.goto("/");
  const link = page.locator(`nav a[href="/c/${id}"]`);
  const item = page.locator("li", { has: page.locator(`a[href="/c/${id}"]`) });
  const title = "Keep This Chat"; // its automatic name (app/chat/titles.py)
  await expect(link).toHaveText(title);

  await item.getByRole("button", { name: /^Rename/ }).click();
  const rename = page.getByRole("dialog", { name: "Rename chat" });
  await rename.getByLabel("Name").fill("This must not stick");
  await rename.getByRole("button", { name: "Cancel" }).click();
  await expect(rename).toBeHidden();
  await expect(link).toHaveText(title);

  await item.getByRole("button", { name: /^Delete/ }).click();
  const remove = page.getByRole("dialog", { name: "Delete this chat?" });
  await remove.getByRole("button", { name: "Cancel" }).click();
  await expect(remove).toBeHidden();
  await page.reload();
  await expect(link).toHaveText(title);
  await page.goto(`/c/${id}`);
  await expect(replies(page)).toHaveCount(1);
});

test("an unknown page shows the not-found screen, with a way back", async ({ page, account: _ }) => {
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "This page could not be found" })).toBeVisible();
  await page.getByRole("link", { name: "Start a new chat" }).click();
  await expect(page).toHaveURL("/");
  await expect(composer(page)).toBeVisible();
});

test("a new chat has no suggested questions; its first message is an ordinary message", async ({ page, account: _ }) => {
  await page.goto("/");
  await expect(page.getByRole("list", { name: "Suggested questions" })).toHaveCount(0);
  await send(page, "Give me the Quadratic Formula");
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  await waitForIdle(page);
  await expect(page.getByRole("article", { name: "You" })).toHaveText(/Give me the Quadratic Formula/);
  await expect(lastReply(page)).toContainText("You said: Give me the Quadratic Formula");
  await expect(chatLinks(page)).toHaveCount(1);
});
