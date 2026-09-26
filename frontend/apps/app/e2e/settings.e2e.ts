/**
 * Settings, end to end: every section saves to the account, survives a reload and shows up in
 * a second browser (another device), and two tabs never overwrite each other unnoticed.
 */

import { type Browser, type Page, expect } from "@playwright/test";

import { APP_URL } from "./env";
import { PASSWORD, SAME_ORIGIN, expectAccessible, expectNoHorizontalOverflow, mailCode, test, uniqueEmail } from "./support";

/** A 48 x 48 PNG (two colours), made with Pillow. */
const PHOTO = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAATklEQVR42u3QsRFAEQBEQaT6ksoV9+Nfk1wJck0wBPsKuNm5OL8cdtT+vmUnhccCAgICAgICAgICAgI6W6xleAgICAgICAgICAgICOheCzTtBVMQB30NAAAAAElFTkSuQmCC",
  "base64",
);

/** The same account signed in from another browser: a second device. */
async function secondDevice(browser: Browser, account: { email: string; password: string }): Promise<Page> {
  const context = await browser.newContext({ baseURL: APP_URL });
  const page = await context.newPage();
  const login = await context.request.post("/api/v1/auth/login", {
    data: { email: account.email, password: account.password },
    headers: { ...SAME_ORIGIN, "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0" },
  });
  expect(login.status()).toBe(200);
  return page;
}

test("the sections: one address each, one heading each, accessible, no sideways scroll", async ({ page, account: _ }) => {
  await page.goto("/settings");
  await expect(page).toHaveURL("/settings/profile");
  for (const [slug, heading] of [
    ["profile", "Profile"],
    ["academic", "Academic Profile"],
    ["goals", "Learning Goals"],
    ["learning", "Learning Preferences"],
    ["tutor", "AI Tutor"],
    ["subjects", "Subjects & Study"],
    ["notifications", "Notifications"],
    ["appearance", "Appearance & Accessibility"],
    ["privacy", "Privacy & Security"],
  ] as const) {
    await page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: heading, exact: true }).click();
    await expect(page).toHaveURL(`/settings/${slug}`);
    await expect(page.getByRole("heading", { level: 2, name: heading })).toBeVisible();
    await expect(page.getByRole("link", { name: heading, exact: true })).toHaveAttribute("aria-current", "page");
    await expectAccessible(page);
    await expectNoHorizontalOverflow(page);
  }
  await page.goto("/settings/nothing-here");
  await expect(page.getByRole("heading", { name: "This page could not be found" })).toBeVisible();
});

test("profile: name and time zone persist, on this device and another", async ({ page, browser, account }) => {
  await page.goto("/settings/profile");
  await page.getByLabel("Display name").fill("Asha Settings");
  await page.getByLabel("Time zone").selectOption("Asia/Kolkata");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Profile saved.")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue("Asha Settings");
  await expect(page.getByLabel("Time zone")).toHaveValue("Asia/Kolkata");

  const other = await secondDevice(browser, account);
  await other.goto("/settings/profile");
  await expect(other.getByLabel("Display name")).toHaveValue("Asha Settings");
  await other.context().close();
});

test("two tabs: a stale save is refused, the edit is kept and saves on the second try", async ({ page, account: _ }) => {
  const tab = await page.context().newPage();
  await page.goto("/settings/profile");
  await tab.goto("/settings/profile");

  await tab.getByLabel("Display name").fill("From the other tab");
  await tab.getByRole("button", { name: "Save", exact: true }).click();
  await expect(tab.getByText("Profile saved.")).toBeVisible();

  await page.getByLabel("Display name").fill("From this tab");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/changed somewhere else/)).toBeVisible();
  await expect(page.getByLabel("Display name")).toHaveValue("From this tab"); // the edit is not lost
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Profile saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue("From this tab");
  await tab.close();
});

test("leaving with unsaved changes asks first", async ({ page, account: _ }) => {
  await page.goto("/settings/profile");
  await page.getByLabel("Display name").fill("Not saved yet");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("link", { name: "Notifications" }).click();
  await expect(page).toHaveURL("/settings/profile");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("link", { name: "Notifications" }).click();
  await expect(page).toHaveURL("/settings/notifications");
});

test("photo: upload, shown in the sidebar, replace-safe, removed", async ({ page, account: _ }) => {
  await page.goto("/settings/profile");
  await page.locator('input[type="file"]').setInputFiles({ name: "me.png", mimeType: "image/png", buffer: PHOTO });
  await expect(page.getByText("Photo updated.")).toBeVisible();
  const photo = page.getByRole("main").locator('img[src^="/api/v1/me/avatar?v="]');
  await expect(photo).toBeVisible();
  const src = await photo.getAttribute("src");
  const response = await page.request.get(src as string);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("image/webp");
  expect(response.headers()["cache-control"]).toContain("immutable");
  await expect(page.locator(`aside img[src="${src}"]`)).toBeVisible(); // the sidebar

  await page.getByRole("button", { name: "Remove photo" }).click();
  await expect(page.getByText("Photo removed.")).toBeVisible();
  await expect(photo).toHaveCount(0);
  expect((await page.request.get(src as string)).status()).toBe(404); // the old address never serves again

  await page.locator('input[type="file"]').setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hi") });
  await expect(page.getByRole("alert").filter({ hasText: "Use a JPEG, PNG or WebP image." })).toBeVisible();
});

test("email: changed only after the code from the new address", async ({ page, account }) => {
  const next = uniqueEmail("moved");
  await page.goto("/settings/profile");
  await page.getByRole("button", { name: "Change email" }).click();
  const dialog = page.getByRole("dialog", { name: "Change your email" });
  await dialog.getByLabel("New email").fill(next);
  await dialog.getByLabel("Current password").fill("not-the-password");
  await dialog.getByRole("button", { name: "Send code" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("That password isn't right.");

  await dialog.getByLabel("Current password").fill(account.password);
  await dialog.getByRole("button", { name: "Send code" }).click();
  const codeStep = page.getByRole("dialog", { name: "Enter the code" });
  await codeStep.getByLabel("Code").fill("000000");
  await codeStep.getByRole("button", { name: "Change email" }).click();
  await expect(codeStep.getByRole("alert")).toHaveText("That code is wrong or has expired.");
  await codeStep.getByLabel("Code").fill(await mailCode(next, "change"));
  await codeStep.getByRole("button", { name: "Change email" }).click();
  await expect(page.getByText(`Your email is now ${next}.`, { exact: false })).toBeVisible();
  await expect(page.getByRole("main").getByText(next)).toBeVisible();

  await page.request.post(`${APP_URL}/api/v1/auth/logout`, { headers: SAME_ORIGIN });
  const old = await page.request.post(`${APP_URL}/api/v1/auth/login`, {
    data: { email: account.email, password: PASSWORD },
    headers: SAME_ORIGIN,
  });
  expect(old.status()).toBe(401);
  const moved = await page.request.post(`${APP_URL}/api/v1/auth/login`, {
    data: { email: next, password: PASSWORD },
    headers: SAME_ORIGIN,
  });
  expect(moved.status()).toBe(200); // signed in again, so the fixture can delete the account
});

test("devices: another device is listed and can be signed out on its own", async ({ page, browser, account }) => {
  const other = await secondDevice(browser, account);
  await page.goto("/settings/privacy");
  const row = page.getByRole("listitem").filter({ hasText: "Firefox on Linux" });
  await expect(row).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "This device" })).toBeVisible();
  await row.getByRole("button", { name: /^Sign out Firefox on Linux/ }).click();
  await expect(page.getByText("Signed out Firefox on Linux.")).toBeVisible();
  await expect(row).toHaveCount(0);
  expect((await other.request.get("/api/v1/me")).status()).toBe(401);
  expect((await page.request.get(`${APP_URL}/api/v1/me`)).status()).toBe(200);
  await other.context().close();
});

test("appearance: applies at once, persists, and follows the account to another device", async ({
  page,
  browser,
  account,
}) => {
  const html = page.locator("html");
  await page.goto("/settings/appearance");
  await page.getByRole("radio", { name: "Dark" }).check();
  await page.getByRole("radio", { name: "Large", exact: true }).check();
  await page.getByRole("switch", { name: "High contrast" }).click();
  await page.getByRole("switch", { name: "Comfortable reading" }).click();
  await expect(html).toHaveClass(/\bdark\b/);
  await expect(html).toHaveAttribute("data-font-size", "large");
  await expect(html).toHaveAttribute("data-contrast", "high");
  await expect(html).toHaveAttribute("data-reading", "comfort");
  await expectAccessible(page); // high contrast, dark

  await expect
    .poll(async () => (await (await page.request.get(`${APP_URL}/api/v1/me/appearance`)).json()).fontSize)
    .toBe("large");
  await page.reload();
  await expect(html).toHaveAttribute("data-font-size", "large");
  await expect(html).toHaveClass(/\bdark\b/);

  const other = await secondDevice(browser, account);
  await other.goto("/");
  await expect(other.locator("html")).toHaveAttribute("data-font-size", "large");
  await expect(other.locator("html")).toHaveAttribute("data-contrast", "high");
  await expect(other.locator("html")).toHaveClass(/\bdark\b/);
  await other.context().close();
});

test("notifications: honest about delivery and time zone, and saved", async ({ page, account: _ }) => {
  await page.goto("/settings/notifications");
  await expect(page.getByText("PadhAI isn't sending notification emails yet.", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Set your time zone" })).toBeVisible();
  const weekly = page.getByRole("switch", { name: "Weekly summary" });
  await expect(weekly).toHaveAttribute("aria-checked", "false");
  await weekly.click();
  await expect(weekly).toHaveAttribute("aria-checked", "true");
  await expect
    .poll(async () => (await (await page.request.get(`${APP_URL}/api/v1/notifications/preferences`)).json()).weeklySummary)
    .toBe(true);
  await page.reload();
  await expect(page.getByRole("switch", { name: "Weekly summary" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("switch", { name: "Sign-in alerts" })).toHaveAttribute("aria-checked", "true");
});

// ------------------------------------------------------------------ learning

async function apiJson(page: Page, path: string) {
  return (await page.request.get(`${APP_URL}/api${path}`)).json();
}

test("academic profile: catalog choices, a state only with a state board, saved", async ({ page, account: _ }) => {
  await page.goto("/settings/academic");
  await page.getByLabel("Class").selectOption({ label: "Class 10" });
  await expect(page.getByLabel("State", { exact: true })).toHaveCount(0);
  await page.getByLabel("Board").selectOption({ label: "State board" });
  await page.getByLabel("State", { exact: true }).selectOption({ label: "Maharashtra" });
  await page.getByLabel("Medium of instruction").selectOption({ label: "Marathi" });
  await page.getByLabel("Academic year").selectOption({ label: "2026–27" });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Academic profile saved.")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Class")).toHaveValue("class_10");
  await expect(page.getByLabel("State", { exact: true })).toHaveValue("maharashtra");

  await page.getByLabel("Board").selectOption({ label: "CBSE" });
  await expect(page.getByLabel("State", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Academic profile saved.")).toBeVisible();
  const profile = await apiJson(page, "/v1/learning/profile");
  expect([profile.board, profile.boardState, profile.medium]).toEqual(["cbse", null, "marathi"]);
});

test("learning goals: topics, study time and goals, saved", async ({ page, account: _ }) => {
  await page.goto("/settings/goals");
  await page.getByLabel("Main goal").selectOption({ label: "Preparing for a competitive exam" });
  await page.getByLabel("Exam you're preparing for").fill("NEET");
  await page.getByLabel("Target score (%)").fill("90");
  const topic = page.getByLabel("Topics you find difficult", { exact: true });
  await topic.fill("Genetics");
  await topic.press("Enter");
  await topic.fill("genetics");
  await topic.press("Enter");
  await expect(page.getByText("That topic is already on the list.")).toBeVisible();
  await topic.fill("Optics");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Remove Genetics" }).click();
  await page.getByLabel("Daily goal (minutes)").fill("45");
  await page.getByLabel("Weekly goal (minutes)").fill("300");
  await page.getByLabel("Preferred study time").fill("18:30");
  await page.getByLabel("Short-term goal").fill("Finish biology revision");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Goals saved.")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Exam you're preparing for")).toHaveValue("NEET");
  await expect(page.getByRole("list", { name: "Your difficult topics" }).getByRole("listitem")).toHaveText(["Optics"]);
  const profile = await apiJson(page, "/v1/learning/profile");
  expect([profile.mainGoal, profile.targetScorePercent, profile.dailyActiveMinutesGoal, profile.preferredStudyTime]).toEqual([
    "competitive_exam",
    90,
    45,
    "18:30",
  ]);
});

test("preferences save as they change, and the preview shows what the tutor is told", async ({ page, account: _ }) => {
  await page.goto("/settings/learning");
  await page.getByRole("group", { name: "Reply language" }).getByRole("radio", { name: "Hindi" }).check();
  await expect.poll(async () => (await apiJson(page, "/v1/learning/preferences")).language).toBe("hindi");

  await page.goto("/settings/tutor");
  await expect(page.getByRole("heading", { name: "What your tutor is told" })).toBeVisible();
  await expect(page.getByText("Reply in Hindi", { exact: false })).toBeVisible();
  await page.getByRole("group", { name: "How it answers problems" }).getByRole("radio", { name: "Hint first" }).check();
  await expect(page.getByText("start with a hint", { exact: false })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("group", { name: "How it answers problems" }).getByRole("radio", { name: "No preference" }).check();
  await expect(page.getByText("start with a hint", { exact: false })).toHaveCount(0);
});

test("subjects: added, reordered from the keyboard, flagged and saved", async ({ page, account: _ }) => {
  await page.goto("/settings/subjects");
  for (const subject of ["Mathematics", "Physics", "Chemistry"]) {
    await page.getByLabel("Add a subject").selectOption({ label: subject });
    await page.getByRole("button", { name: "Add", exact: true }).click();
  }
  const rows = page.getByRole("list", { name: "Your subjects" }).getByRole("listitem");
  await expect(rows).toHaveCount(3);

  const up = page.getByRole("button", { name: "Move Chemistry up" });
  await up.focus();
  await page.keyboard.press("Enter");
  await expect(up).toBeFocused(); // focus follows the subject it moved
  await page.keyboard.press("Enter");
  await expect(rows.first()).toContainText("Chemistry");
  await expect(page.getByRole("button", { name: "Move Chemistry down" })).toBeFocused(); // at the top: up is disabled

  await page.getByRole("checkbox", { name: "Priority: Physics" }).check();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Subjects saved.")).toBeVisible();

  await page.reload();
  await expect(rows).toHaveCount(3);
  const saved = await apiJson(page, "/v1/learning/subjects");
  expect(saved.items.map((item: { code: string }) => item.code)).toEqual(["chemistry", "mathematics", "physics"]);
  expect(saved.items[2].isPriority).toBe(true);

  await page.getByRole("button", { name: "Remove Mathematics" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Subjects saved.")).toBeVisible();
  expect((await apiJson(page, "/v1/learning/subjects")).items).toHaveLength(2);
});
