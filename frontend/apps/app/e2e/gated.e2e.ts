import { expect, test } from "./support";

/**
 * The MAIN server runs as production does, with PREVIEW_FEATURES off
 * (e2e/serve.mjs forces it). Nothing built ahead of its backend may show:
 * no learning-tool pages, no sample numbers, no "Preview"/"Soon" controls.
 * preview.e2e.ts checks the same build with the switch on.
 */
const TOOL_PATHS = ["/homework", "/summarizer"];

test("without preview features the learning tools do not exist", async ({ page, account: _ }) => {
  for (const path of TOOL_PATHS) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(404);
    await expect(page.getByRole("heading", { name: "This page could not be found" })).toBeVisible();
  }
});

test("without preview features no sample data or unconnected control is shown", async ({ page, account: _ }) => {
  for (const path of ["/", "/settings"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // No tool besides the chat, so no Learning Hub (the chat is never listed as a tool of its own).
    await expect(page.getByRole("navigation", { name: "Learning Hub" })).toHaveCount(0);
    for (const text of [/Day Streak/, /\bXP\b/, /Leaderboard/, /Syllabus Synchronized/, /Class 10 •/]) {
      await expect(page.getByText(text), `${text} on ${path}`).toHaveCount(0);
    }
    await expect(page.getByText(/^(Preview|Soon)$/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /coming soon/i })).toHaveCount(0);
  }
});
