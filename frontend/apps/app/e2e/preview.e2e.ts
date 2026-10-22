import { PREVIEW_URL } from "./env";
import { composer, expect, expectAccessible, expectNoHorizontalOverflow, test } from "./support";

/**
 * The PREVIEW server (:3101, PREVIEW_FEATURES=1): the UI built ahead of its
 * backend. It must say on screen that it is sample data, meet the same
 * accessibility bar as the rest, and never touch the API for its sample data.
 * gated.e2e.ts checks the other half: none of this exists on the real server.
 */
const TOOLS = [
  { path: "/homework", title: "Homework Helper" },
  { path: "/summarizer", title: "Summarizer" },
];

const SHELL_CALLS = new Set([
  "/api/auth/get-session", // SessionKeeper: once per page load, keeps the session and its cookie in step
  "/api/v1/conversations",
  "/api/v1/progress",
  "/api/v1/progress/activity",
  "/api/v1/progress/streak",
  "/api/v1/notifications",
  // Study time (features/study): the header's session state and its beat, on every page of the shell.
  "/api/v1/study/session",
  "/api/v1/study/beat",
]);

test.beforeAll(async () => {
  // serve.mjs starts this server alongside the main one; give it the same chance to come up.
  await expect
    .poll(async () => (await fetch(`${PREVIEW_URL}/login`).catch(() => null))?.ok ?? false, { timeout: 60_000 })
    .toBe(true);
});

test("the shell lists every tool, and marks what is not real", async ({ page, account: _ }) => {
  await page.goto("/");
  await expect(composer(page)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Learning Hub" }).getByRole("link")).toHaveCount(TOOLS.length); // not the chat itself
  await expect(page.getByRole("banner").getByRole("link", { name: /day learning streak/ })).toBeVisible(); // the real one
  await expect(page.getByRole("button", { name: /Leaderboard/ })).toBeDisabled();
  // Attach and dictation are real now (not preview): the same, enabled buttons in both modes.
  await expect(page.getByRole("button", { name: "Attach files" })).toBeEnabled();
  await expect(page.getByText("Preview", { exact: true }).first()).toBeVisible();
  await expectAccessible(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
});

for (const tool of TOOLS) {
  test(`${tool.title}: marked as sample data, accessible, fits a phone, calls no API`, async ({ page, account: _ }) => {
    const calls: string[] = [];
    page.on("request", (request) => {
      const { pathname } = new URL(request.url());
      // The shell's own chat list and streak may refresh; the tool itself must not call anything.
      if (pathname.startsWith("/api/") && !SHELL_CALLS.has(pathname)) calls.push(`${request.method()} ${pathname}`);
    });

    await page.goto(tool.path);
    await expect(page.getByRole("heading", { level: 1, name: tool.title })).toBeVisible();
    await expect(page.getByRole("note")).toContainText("Sample data, not connected yet");
    await expect(page.getByRole("navigation", { name: "Learning Hub" }).getByRole("link", { name: new RegExp(tool.title) })).toHaveAttribute(
      "aria-current",
      "page",
    );
    for (const button of await page.getByRole("main").getByRole("button", { name: /Soon/ }).all()) {
      await expect(button).toBeDisabled();
    }
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await expectAccessible(page);

    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);

    expect(calls, "the tool page made no API calls").toEqual([]);
  });
}
