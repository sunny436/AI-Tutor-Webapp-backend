import {
  LONG_MESSAGE,
  PASSWORD,
  composer,
  conversationIdOf,
  emptyGreeting,
  expect,
  expectStudyGreeting,
  lastReply,
  logOutFromSidebar,
  mailCode,
  openSettingsFromSidebar,
  replies,
  send,
  sendAndWait,
  stopButton,
  test,
  uniqueEmail,
  waitForIdle,
} from "./support";

const MARKDOWN = [
  "Here is **bold**, *italic*, `inline code` and a [link](https://example.com).",
  "",
  "| Name | Value |",
  "| --- | --- |",
  "| alpha | 1 |",
  "",
  "```python",
  "print('hello')",
  "```",
  "",
  "Inline math $a^2 + b^2 = c^2$ and a block:",
  "",
  "$$",
  "\\int_0^1 x\\,dx",
  "$$",
].join("\n");

/**
 * One user, start to finish: sign up, chat, stop, regenerate, copy, rate, reload,
 * rename, a second chat, switching mid-reply, delete, sign out and back in, reset
 * the password, change the name, delete the account.
 */
test("a user's whole journey", async ({ page, context }) => {
  test.setTimeout(240_000);
  const email = uniqueEmail("journey");
  const newPassword = `${PASSWORD}-new`;

  await test.step("sign up: email, the emailed code, then a password", async () => {
    await page.goto("/signup");
    await page.getByLabel("Name (optional)").fill("E2E Journey");
    await page.getByLabel("Email").fill(email);
    await page.getByRole("button", { name: "Send code" }).click();
    await expect(page.getByRole("status")).toContainText("a 6-digit code is on its way");
    await page.getByLabel("Code").fill(await mailCode(email, "signin"));
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("heading", { name: "Choose a password" })).toBeVisible();
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Save password" }).click();
    await expect(page).toHaveURL("/");
    await expectStudyGreeting(page);
  });

  await test.step("the session is an httpOnly cookie the page cannot read, and no answer carries it", async () => {
    const session = (await context.cookies()).find((cookie) => cookie.name === "padhai_session");
    expect(session, "session cookie").toBeTruthy();
    expect(session?.httpOnly).toBe(true);
    expect(session?.sameSite).toBe("Lax");
    const visible = await page.evaluate(() => ({
      cookie: document.cookie,
      storage: JSON.stringify({ ...window.localStorage, ...window.sessionStorage }),
    }));
    expect(visible.cookie).not.toContain("padhai_session");
    expect(visible.storage).not.toContain(session?.value ?? "<none>");
    const token = decodeURIComponent(session?.value ?? "").split(".")[0] ?? "<none>";
    const answer = await page.request.get("/api/auth/get-session");
    expect(answer.status()).toBe(200);
    expect(await answer.text()).not.toContain(token);
  });

  let first = "";
  await test.step("a new chat streams a reply that renders Markdown, tables, code and maths", async () => {
    await composer(page).fill(MARKDOWN);
    await composer(page).press("Enter"); // Enter sends
    await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
    first = conversationIdOf(page);
    await waitForIdle(page);

    const reply = lastReply(page);
    await expect(reply).toContainText("You said: Here is");
    await expect(reply.locator("strong")).toHaveText("bold");
    await expect(reply.locator("em")).toHaveText("italic");
    const link = reply.getByRole("link", { name: "link" });
    await expect(link).toHaveAttribute("href", "https://example.com");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
    await expect(reply.getByRole("table")).toContainText("alpha");
    await expect(reply.locator("pre code.language-python")).toContainText("print('hello')");
    await expect(reply.getByRole("button", { name: "Copy code" })).toBeVisible();
    await expect(reply.locator(".katex-display")).toHaveCount(1);
    expect(await reply.locator(".katex").count()).toBeGreaterThanOrEqual(2);
    await expect(reply.locator(".katex-error")).toHaveCount(0);

    // The chat is in the sidebar under the title the server gave it.
    await expect(page.locator(`nav a[href="/c/${first}"]`)).toBeVisible();
  });

  await test.step("Shift+Enter adds a line instead of sending", async () => {
    await composer(page).fill("line one");
    await composer(page).press("Shift+Enter");
    await composer(page).pressSequentially("line two");
    await expect(composer(page)).toHaveValue("line one\nline two");
    await composer(page).fill("");
  });

  await test.step("Stop keeps what was written and marks it stopped", async () => {
    await send(page, LONG_MESSAGE);
    await expect(lastReply(page)).toContainText("w5");
    await stopButton(page).click();
    await expect(lastReply(page)).toContainText("Stopped");
    await waitForIdle(page);
    await expect(lastReply(page)).not.toContainText("w80");
  });

  await test.step("the stopped reply is still stopped after a reload", async () => {
    await page.reload();
    await expect(lastReply(page)).toContainText("Stopped");
    await expect(lastReply(page)).not.toContainText("w80");
  });

  await test.step("Regenerate replaces the last reply", async () => {
    await lastReply(page).getByRole("button", { name: "Regenerate reply" }).click();
    await expect(lastReply(page)).toContainText("w80", { timeout: 30_000 });
    await waitForIdle(page);
    await expect(lastReply(page)).not.toContainText("Stopped");
    await expect(replies(page)).toHaveCount(2);
  });

  await test.step("Copy puts the reply's Markdown on the clipboard", async () => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await lastReply(page).getByRole("button", { name: "Copy reply" }).click();
    await expect(lastReply(page).getByRole("button", { name: "Copied" })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`You said: ${LONG_MESSAGE}`);
  });

  await test.step("thumbs up, then clear it", async () => {
    const good = lastReply(page).getByRole("button", { name: "Good reply" });
    const saved = page.waitForResponse((response) => /\/feedback$/.test(response.url()) && response.request().method() === "PUT");
    await good.click();
    expect((await saved).status()).toBe(200);
    await expect(good).toHaveAttribute("aria-pressed", "true");

    const cleared = page.waitForResponse((response) => /\/feedback$/.test(response.url()) && response.request().method() === "DELETE");
    await good.click();
    expect((await cleared).status()).toBe(204);
    await expect(good).toHaveAttribute("aria-pressed", "false");
  });

  await test.step("the conversation is still there after a reload", async () => {
    await page.reload();
    await expect(page.getByRole("article", { name: "You" })).toHaveCount(2);
    await expect(replies(page)).toHaveCount(2);
    await expect(replies(page).first().getByRole("table")).toContainText("alpha");
    await expect(lastReply(page)).toContainText("w80");
  });

  await test.step("rename the chat", async () => {
    const item = page.locator("li", { has: page.locator(`a[href="/c/${first}"]`) });
    await item.getByRole("button", { name: /^Rename/ }).click();
    const dialog = page.getByRole("dialog", { name: "Rename chat" });
    await dialog.getByLabel("Name").fill("Renamed by E2E");
    // The rename shows at once (optimistic); wait for it to be saved before reloading, or the
    // reload cancels the request and the old name comes back.
    const renamed = page.waitForResponse(
      (response) => response.url().endsWith(`/conversations/${first}`) && response.request().method() === "PATCH",
    );
    await dialog.getByRole("button", { name: "Rename" }).click();
    expect((await renamed).status()).toBe(200);
    await expect(page.locator(`nav a[href="/c/${first}"]`)).toHaveText("Renamed by E2E");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Renamed by E2E");
    await expect(page).toHaveTitle(/^Renamed by E2E · /);
    await page.reload();
    await expect(page.locator(`nav a[href="/c/${first}"]`)).toHaveText("Renamed by E2E");
  });

  let second = "";
  await test.step("start a second chat", async () => {
    await page.getByRole("link", { name: "Ask New Doubt" }).click();
    await expect(page).toHaveURL("/");
    await expectStudyGreeting(page);
    await sendAndWait(page, "A second chat");
    second = conversationIdOf(page);
    expect(second).not.toBe(first);
    await expect(page.locator("nav a[href^='/c/']")).toHaveCount(2);
  });

  await test.step("switching chats mid-reply leaves the other chat usable, and the reply finishes", async () => {
    await send(page, LONG_MESSAGE);
    await expect(lastReply(page)).toContainText("w3");

    await page.locator(`nav a[href="/c/${first}"]`).click();
    await expect(page).toHaveURL(`/c/${first}`);
    await expect(stopButton(page)).toHaveCount(0);
    await sendAndWait(page, "Hello again");
    await expect(lastReply(page)).toContainText("You said: Hello again");

    await page.locator(`nav a[href="/c/${second}"]`).click();
    await expect(lastReply(page)).toContainText("w80", { timeout: 30_000 });
    await waitForIdle(page);
    await expect(lastReply(page)).not.toContainText("Stopped");
  });

  await test.step("delete the chat on screen", async () => {
    const item = page.locator("li", { has: page.locator(`a[href="/c/${second}"]`) });
    await item.getByRole("button", { name: /^Delete/ }).click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page).toHaveURL("/");
    await expect(page.locator(`nav a[href="/c/${second}"]`)).toHaveCount(0);
    await page.goto(`/c/${second}`);
    await expect(page.getByRole("heading", { name: "This chat isn't available" })).toBeVisible();
  });

  await test.step("log out; a chat link then asks to sign in and comes back", async () => {
    await logOutFromSidebar(page);
    await expect(page).toHaveURL("/login");
    expect((await context.cookies()).some((cookie) => cookie.name === "padhai_session" && cookie.value)).toBe(false);

    await page.goto(`/c/${first}`);
    await expect(page).toHaveURL(`/login?redirect=${encodeURIComponent(`/c/${first}`)}`);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(`/c/${first}`);
    await expect(lastReply(page)).toContainText("You said: Hello again");
  });

  await test.step("forgotten password: reset it with an emailed code", async () => {
    await logOutFromSidebar(page);
    await expect(page).toHaveURL("/login");
    await page.getByRole("button", { name: "Forgot password?" }).click();
    await page.getByLabel("Email").fill(email);
    await page.getByRole("button", { name: "Send reset code" }).click();
    await expect(page.getByRole("status")).toContainText("a reset code is on its way");
    await page.getByLabel("Code").fill(await mailCode(email, "reset"));
    await page.getByLabel("New password").fill(newPassword);
    await page.getByRole("button", { name: "Set new password" }).click();
    await expect(page).toHaveURL("/");
    await expect(page.locator(`nav a[href="/c/${first}"]`)).toBeVisible();
  });

  await test.step("change the display name in Settings", async () => {
    await openSettingsFromSidebar(page);
    await expect(page).toHaveURL("/settings/profile");
    await page.getByLabel("Display name").fill("E2E Renamed");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Profile saved.")).toBeVisible();
    await expect(page.getByText("E2E Renamed", { exact: true })).toBeVisible();
  });

  await test.step("delete the account", async () => {
    await page.getByRole("link", { name: "Privacy & Security" }).click();
    await page.getByRole("button", { name: "Delete account" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete your account?" });
    await dialog.getByLabel("Password").fill(newPassword);
    await dialog.getByRole("button", { name: "Delete account" }).click();
    await expect(page).toHaveURL("/login?reason=deleted");
    await expect(page.getByRole("status")).toContainText("Your account and its chats have been deleted.");
    expect((await page.request.get("/api/v1/me")).status()).toBe(401);
  });
});
