/**
 * Settings, end to end: every section saves to the account, survives a reload and shows up in
 * a second browser (another device), and two tabs never overwrite each other unnoticed.
 *
 * The learning sections have exactly one test each (Academic Profile, Learning Goals, Learning
 * Preferences, AI Tutor, Subjects & Study, Progress & Goals, Notifications; Learning & Streak is
 * in streak.e2e.ts). One test is one section's whole workflow, not one assertion: it keeps every
 * check of the tests it replaced, and ends where the setting takes effect: what the tutor is told
 * (`tutorKnows`), or, for Notifications, that nothing of it reaches the tutor.
 */

import { type Browser, type Page, expect } from "@playwright/test";

import { APP_URL } from "./env";
import {
  PASSWORD,
  SAME_ORIGIN,
  expectAccessible,
  expectNoHorizontalOverflow,
  mailCode,
  openSettingsFromSidebar,
  sendAndWait,
  test,
  tutorKnows,
  uniqueEmail,
} from "./support";

/** A 48 x 48 PNG (two colours), made with Pillow. */
const PHOTO = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAATklEQVR42u3QsRFAEQBEQaT6ksoV9+Nfk1wJck0wBPsKuNm5OL8cdtT+vmUnhccCAgICAgICAgICAgI6W6xleAgICAgICAgICAgICOheCzTtBVMQB30NAAAAAElFTkSuQmCC",
  "base64",
);

/** The same account signed in from another browser: a second device. */
async function secondDevice(browser: Browser, account: { email: string; password: string }): Promise<Page> {
  const context = await browser.newContext({ baseURL: APP_URL });
  const page = await context.newPage();
  const login = await context.request.post("/api/auth/sign-in/email", {
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
    ["progress", "Progress & Goals"],
    ["study-tracking", "Study Tracking"],
    ["streak", "Learning & Streak"],
    ["notifications", "Notifications"],
    ["appearance", "Appearance & Accessibility"],
    ["privacy", "Privacy & Security"],
    ["help", "Help & Support"],
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

test("photo: upload, shown with the account, replace-safe, removed", async ({ page, account: _ }) => {
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
  await expect(page.locator(`aside img[src="${src}"]`)).toBeVisible(); // the Settings panel's account

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
  const old = await page.request.post(`${APP_URL}/api/auth/sign-in/email`, {
    data: { email: account.email, password: PASSWORD },
    headers: SAME_ORIGIN,
  });
  expect(old.status()).toBe(401);
  const moved = await page.request.post(`${APP_URL}/api/auth/sign-in/email`, {
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

test("notifications: honest about delivery, saved here and on another device, and never told to the tutor", async ({
  page,
  browser,
  account,
}) => {
  const saved = async (target: Page) => (await target.request.get(`${APP_URL}/api/v1/notifications/preferences`)).json();
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

  // Reminders in the app: off here, still off on another device, and back on from there.
  const inApp = (target: Page) => target.getByRole("switch", { name: "Reminders in the app" });
  await expect(inApp(page)).toBeChecked();
  await inApp(page).click();
  await expect.poll(async () => (await saved(page)).inAppReminders).toBe(false);
  await page.reload();
  await expect(inApp(page)).not.toBeChecked();
  const other = await secondDevice(browser, account);
  await other.goto("/settings/notifications");
  await expect(inApp(other)).not.toBeChecked();
  await inApp(other).click();
  await expect.poll(async () => (await saved(other)).inAppReminders).toBe(true);
  await other.context().close();
  await page.reload();
  await expect(inApp(page)).toBeChecked();

  // Delivery settings, not teaching: nothing of them reaches the tutor.
  expect(await tutorKnows(page)).not.toMatch(/reminder|summary|alert|notification/i);
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
  const told = await tutorKnows(page);
  for (const line of [
    "Class: Class 10",
    "Board: State board (Maharashtra)",
    "Medium of instruction at school: Marathi",
    "Academic year: 2026–27",
  ]) {
    expect(told).toContain(line);
  }

  await page.goto("/settings/academic");
  await page.getByLabel("Board").selectOption({ label: "CBSE" });
  await expect(page.getByLabel("State", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Academic profile saved.")).toBeVisible();
  const profile = await apiJson(page, "/v1/learning/profile");
  expect([profile.board, profile.boardState, profile.medium]).toEqual(["cbse", null, "marathi"]);
  const now = await tutorKnows(page);
  expect(now).toContain("Board: CBSE");
  expect(now).not.toContain("Maharashtra");
});

test("learning goals: topics, study time and goals, saved", async ({ page, account: _ }) => {
  // Within the API's window for an exam date: from today to two years ahead.
  const exam = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10);
  await page.goto("/settings/goals");
  await page.getByLabel("Main goal").selectOption({ label: "Preparing for a competitive exam" });
  await page.getByLabel("Exam you're preparing for").fill("NEET");
  await page.getByLabel("Exam date").fill(exam);
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
  await expect(page.getByLabel("Exam date")).toHaveValue(exam);
  await expect(page.getByRole("list", { name: "Your difficult topics" }).getByRole("listitem")).toHaveText(["Optics"]);
  const profile = await apiJson(page, "/v1/learning/profile");
  expect([
    profile.mainGoal,
    profile.targetScorePercent,
    profile.dailyActiveMinutesGoal,
    profile.preferredStudyTime,
    profile.examDate,
  ]).toEqual(["competitive_exam", 90, 45, "18:30", exam]);
  const told = await tutorKnows(page);
  for (const line of [
    "Main goal: preparing for a competitive exam",
    'Preparing for: "NEET"',
    "Target score: 90%",
    'Topics they find difficult: "Optics"',
    'Short-term goal: "Finish biology revision"',
    "Study time: aims for 45 min a day and 300 min a week; usually studies around 6:30 pm",
  ]) {
    expect(told).toContain(line);
  }
});

test("learning preferences: saved as they change, in the preview, and told to the tutor", async ({ page, account: _ }) => {
  const language = page.getByRole("group", { name: "Reply language" });
  await page.goto("/settings/learning");
  await language.getByRole("radio", { name: "Hindi" }).check();
  await expect.poll(async () => (await apiJson(page, "/v1/learning/preferences")).language).toBe("hindi");

  await page.goto("/settings/tutor");
  await expect(page.getByText("Reply in Hindi", { exact: false })).toBeVisible();
  expect(await tutorKnows(page)).toContain("Reply in Hindi");

  await page.goto("/settings/learning");
  await language.getByRole("radio", { name: "No preference" }).check();
  await expect.poll(async () => (await apiJson(page, "/v1/learning/preferences")).language).toBe("auto");
  expect(await tutorKnows(page)).not.toContain("Reply in Hindi");
});

test("AI tutor: choices save, the preview shows what the tutor is told, and the chat is told the same", async ({
  page,
  account: _,
}) => {
  const answers = page.getByRole("group", { name: "How it answers problems" });
  await page.goto("/settings/tutor");
  await expect(page.getByRole("heading", { name: "What your tutor is told" })).toBeVisible();
  await answers.getByRole("radio", { name: "Hint first" }).check();
  await expect(page.getByText("start with a hint", { exact: false })).toBeVisible();
  await expectAccessible(page);
  await expect.poll(async () => (await apiJson(page, "/v1/learning/preferences")).answerMode).toBe("hints_first");
  expect(await tutorKnows(page)).toContain("start with a hint");

  await page.goto("/settings/tutor");
  await answers.getByRole("radio", { name: "No preference" }).check();
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
  expect(await tutorKnows(page)).toContain("Subjects: Chemistry, Mathematics, Physics (a priority)");

  await page.goto("/settings/subjects");
  await page.getByRole("button", { name: "Remove Mathematics" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Subjects saved.")).toBeVisible();
  expect((await apiJson(page, "/v1/learning/subjects")).items).toHaveLength(2);
});

// ------------------------------------------------------------------ progress

const headerStreak = (page: Page) => page.getByRole("banner").getByRole("link", { name: /day learning streak/ });
/** A number on the Progress page, by its label (the first, when Today and This week share one). */
const stat = (page: Page, label: string) =>
  page.locator("dt", { hasText: new RegExp(`^${label}$`) }).first().locator("xpath=following-sibling::dd");

test("progress: a question and an active minute count today, and the tutor is told how the student is doing", async ({
  page,
  account: _,
}) => {
  await page.goto("/");
  await sendAndWait(page, "What is photosynthesis?");
  const report = await page.request.post(`${APP_URL}/api/v1/progress/activity`, { headers: SAME_ORIGIN });
  expect(report.status()).toBe(200);
  expect((await report.json()).credited).toBe(true);
  await page.reload();
  await expect(headerStreak(page)).toHaveAccessibleName(/^1 day learning streak$/);
  const chat = new URL(page.url()).pathname;

  await openSettingsFromSidebar(page);
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: "Progress & Goals" }).click();
  await expect(page).toHaveURL("/settings/progress");
  await expect(page.getByText("about 1 min").first()).toBeVisible();
  await expect(stat(page, "question")).toHaveText("1");
  await expect(page.getByRole("link", { name: "Learning & Streak" }).last()).toBeVisible();

  // The chart: one tab stop, arrow keys move between days, and every value is in the table too.
  const bars = page.getByRole("group", { name: /Active minutes, last 14 days/ }).getByRole("img");
  await expect(bars).toHaveCount(14);
  await bars.last().focus();
  await expect(bars.last()).toHaveAttribute("aria-label", /: 1 min active, 1 question$/);
  await page.keyboard.press("ArrowLeft");
  await expect(bars.nth(12)).toBeFocused();
  await expect(bars.nth(12)).toHaveAttribute("aria-label", /: 0 min active, 0 questions$/);
  await page.keyboard.press("End");
  await expect(bars.last()).toBeFocused();
  await page.getByRole("button", { name: "Show as table" }).click();
  const rows = page.getByRole("table").getByRole("row");
  await expect(rows).toHaveCount(15);
  await expect(rows.nth(1)).toContainText("1 min");
  await expectAccessible(page);
  await expectNoHorizontalOverflow(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await expectAccessible(page);
  await page.emulateMedia({ colorScheme: "light" });

  await page.getByRole("link", { name: "Close settings" }).click();
  await expect(page).toHaveURL(chat);
  await expect(page.getByRole("navigation", { name: "Recent Doubts" })).toBeVisible();
  // Before this question is counted: the one real question, and the minute (or more) credited.
  expect(await tutorKnows(page)).toMatch(/Learning so far: a 1-day learning streak; today \d+ min active and 1 question/);
});

test("the heartbeat reports a minute while PadhAI is used, and stops when it isn't", async ({ page, account: _ }) => {
  const reports: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/progress/activity") reports.push(request.url());
  });
  await page.clock.install();
  await page.goto("/settings/progress");
  await expect(stat(page, "questions?")).toBeVisible();
  await page.getByRole("heading", { level: 2, name: "Progress & Goals" }).click();

  await page.clock.runFor(61_000);
  await expect.poll(() => reports.length).toBe(1);
  // A credited minute refreshes what is on screen.
  await expect(page.getByText("about 1 min").first()).toBeVisible();

  // Nobody touches it: reports stop within the two-minute window, and stay stopped.
  await page.clock.runFor(4 * 60_000);
  const afterIdle = reports.length;
  expect(afterIdle).toBeLessThanOrEqual(2);
  await page.clock.runFor(5 * 60_000);
  expect(reports.length).toBe(afterIdle);
});

// ------------------------------------------------------------------ help

test("help: a support request is sent once, even when the answer is lost, with a reference", async ({ page, account: _ }) => {
  await page.goto("/settings/help");
  await expect(page.getByRole("link", { name: "Help & FAQ" })).toHaveAttribute("href", "/help");
  await expect(page.getByRole("link", { name: "About PadhAI" })).toHaveAttribute("href", "/about");
  await expect(page.getByRole("link", { name: /Terms of Service|Privacy Policy/ })).toHaveCount(0); // not published yet

  await page.getByRole("radio", { name: "Something isn't working" }).check();
  await page.getByLabel("Subject").fill("The chart looks odd");
  await page.getByLabel("Message").fill("Too short");
  await expect(page.getByText("Write at least 10 characters.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.getByLabel("Message").fill("The progress chart shows no bar for today although I asked a question.");
  await expectAccessible(page);

  // The first answer is lost on the way back (the request reached the API); sending again
  // must not make a second request, and must show the first one's reference.
  const bodies: { requestId: string }[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/v1/support/requests")) bodies.push(request.postDataJSON());
  });
  let firstId = "";
  await page.route(
    "**/api/v1/support/requests",
    async (route) => {
      firstId = (await (await route.fetch()).json()).id;
      await route.abort("connectionreset");
    },
    { times: 1 },
  );
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "couldn't reach the server" })).toBeVisible();
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("We've received your request.")).toBeVisible();
  expect(bodies).toHaveLength(2);
  expect(bodies[1]?.requestId).toBe(bodies[0]?.requestId);
  expect(firstId).not.toBe("");
  await expect(page.getByText(firstId.replaceAll("-", "").slice(0, 8).toUpperCase(), { exact: true })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("button", { name: "Send another" }).click();
  await expect(page.getByLabel("Subject")).toHaveValue("");
});

for (const { path, h1, h2 } of [
  { path: "/help", h1: "Help", h2: "Help & FAQ" },
  { path: "/about", h1: "About", h2: "About PadhAI" },
]) {
  test(`${h2}: readable, accessible, fits a phone`, async ({ page, account: _ }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: h1, exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: h2 })).toBeVisible();
    if (path === "/help") {
      await page.getByText("How is active time measured?").click();
      await expect(page.getByText(/A minute counts when PadhAI is open and on screen/)).toBeVisible();
    }
    await expectAccessible(page);
    await page.setViewportSize({ width: 320, height: 700 });
    await expectNoHorizontalOverflow(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await expectAccessible(page);
  });
}

// ------------------------------------------------------------------ unsubscribe

function fakeToken(kind: string): string {
  const payload = Buffer.from(`00000000-0000-4000-8000-000000000000:${kind}`).toString("base64url");
  return `${payload}.${"0".repeat(32)}`;
}

test("unsubscribe: works signed out, asks first, refuses a link we didn't sign", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: APP_URL });
  const page = await context.newPage();
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/notifications/unsubscribe")) posts.push(request.url());
  });

  await page.goto(`/unsubscribe?token=${fakeToken("daily_reminder")}`);
  await expect(page).toHaveURL(/\/unsubscribe\?token=/); // not sent to sign in
  await expect(page.getByRole("heading", { level: 1, name: "Stop daily study reminders?" })).toBeVisible();
  expect(posts).toHaveLength(0); // opening the link changes nothing
  await expectAccessible(page);
  await page.getByRole("button", { name: "Unsubscribe" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "This link doesn't work" })).toBeFocused();
  expect(posts).toHaveLength(1);

  // A link the API accepts. Signing one needs the server's key, so the answer is stubbed here;
  // the API's own tests cover real tokens.
  await page.route("**/api/v1/notifications/unsubscribe", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ kind: "weekly_summary" }) }),
  );
  await page.goto(`/unsubscribe?token=${fakeToken("weekly_summary")}`);
  await page.getByRole("button", { name: "Unsubscribe" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "You're unsubscribed" })).toBeFocused();
  await expect(page.getByText("You won't get weekly summaries from PadhAI any more.", { exact: false })).toBeVisible();
  await expectAccessible(page);

  await page.goto("/unsubscribe");
  await expect(page.getByRole("heading", { level: 1, name: "This link is incomplete" })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 700 });
  await expectNoHorizontalOverflow(page);
  await context.close();
});
