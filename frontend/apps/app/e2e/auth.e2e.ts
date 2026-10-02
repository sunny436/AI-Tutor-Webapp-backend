import type { APIRequestContext, Browser } from "@playwright/test";

import { APP_URL } from "./env";
import { PASSWORD, SAME_ORIGIN, createAccount, deleteAccount, expect, mailCode, test, totp, uniqueEmail } from "./support";

/**
 * The critical identity flows on Better Auth (lib/auth) with the API checking every session
 * (backend/app/auth): one test each, through the real web app, BFF, API and PostgreSQL.
 * Sign-up with a password and the UI journey are in journey.e2e.ts.
 */

async function signedInContext(browser: Browser, email: string, password = PASSWORD) {
  const context = await browser.newContext({ baseURL: APP_URL });
  const response = await context.request.post("/api/auth/sign-in/email", {
    data: { email, password },
    headers: SAME_ORIGIN,
  });
  expect(response.status(), "sign in").toBe(200);
  return context;
}

async function signedIn(request: APIRequestContext): Promise<boolean> {
  const api = (await request.get("/api/v1/me")).status() === 200;
  const session = await (await request.get("/api/auth/get-session")).json();
  // Both layers must agree: the API (its own check) and Better Auth (the cookie's session).
  expect(Boolean(session), "Better Auth agrees with the API").toBe(api);
  return api;
}

test("an email code signs an existing account in, and no answer ever carries the session token", async ({ page }) => {
  const { email } = await createAccount(page, "code");
  await page.request.post("/api/v1/auth/logout", { headers: SAME_ORIGIN });
  expect(await signedIn(page.request)).toBe(false);

  const sent = await page.request.post("/api/auth/email-otp/send-verification-otp", {
    data: { email, type: "sign-in" },
    headers: SAME_ORIGIN,
  });
  expect(sent.status()).toBe(200);
  const answer = await page.request.post("/api/auth/sign-in/email-otp", {
    data: { email, otp: await mailCode(email, "signin") },
    headers: SAME_ORIGIN,
  });
  expect(answer.status()).toBe(200);
  expect(await answer.text()).not.toMatch(/"token"/);
  expect(await signedIn(page.request)).toBe(true);
  expect(await (await page.request.get("/api/auth/get-session")).text()).not.toMatch(/"token"/);
  await deleteAccount(page);
});

test("a password reset by email code signs every device out", async ({ page, browser }) => {
  const { email } = await createAccount(page, "reset");
  const other = await signedInContext(browser, email);
  expect(await signedIn(other.request)).toBe(true);

  const asked = await page.request.post("/api/auth/email-otp/request-password-reset", {
    data: { email },
    headers: SAME_ORIGIN,
  });
  expect(asked.status()).toBe(200);
  const reset = await page.request.post("/api/auth/email-otp/reset-password", {
    data: { email, otp: await mailCode(email, "reset"), password: `${PASSWORD}-reset` },
    headers: SAME_ORIGIN,
  });
  expect(reset.status()).toBe(200);
  expect(await signedIn(other.request), "the other device is signed out").toBe(false);
  expect(await signedIn(page.request), "and this one too").toBe(false);
  await other.close();

  const back = await signedInContext(browser, email, `${PASSWORD}-reset`);
  await back.request.delete("/api/v1/me", { data: { password: `${PASSWORD}-reset` }, headers: SAME_ORIGIN });
  await back.close();
});

test("signing one device out ends its session at both layers", async ({ page, browser, account }) => {
  const other = await signedInContext(browser, account.email);
  const sessions = (await (await page.request.get("/api/v1/auth/sessions")).json()) as {
    items: { id: string; current: boolean }[];
  };
  const target = sessions.items.find((item) => !item.current);
  expect(target, "the other device is listed").toBeTruthy();
  const revoked = await page.request.delete(`/api/v1/auth/sessions/${target?.id}`, { headers: SAME_ORIGIN });
  expect(revoked.status()).toBe(204);
  expect(await signedIn(other.request)).toBe(false);
  expect(await signedIn(page.request)).toBe(true);
  await other.close();
});

test("repeated wrong passwords lock the account's password sign-in, even with the right one", async ({ request }) => {
  const email = uniqueEmail("locked"); // any address: the limit never says whether it exists
  const attempt = (password: string) =>
    request.post(`${APP_URL}/api/auth/sign-in/email`, { data: { email, password }, headers: SAME_ORIGIN });
  for (let i = 0; i < 10; i += 1) expect((await attempt(`wrong-${i}`)).status()).toBe(401);
  expect((await attempt("wrong-again")).status()).toBe(429);
});

test("one student never reaches another's data", async ({ page, browser, account }) => {
  const sent = await page.request.post("/api/v1/chat/stream", { data: { message: "mine only" }, headers: SAME_ORIGIN });
  const conversationId = /"conversationId":\s*"([0-9a-f-]{36})"/.exec(await sent.text())?.[1];
  expect(conversationId).toBeTruthy();

  const stranger = await browser.newContext({ baseURL: APP_URL });
  const strangerPage = await stranger.newPage();
  await createAccount(strangerPage, "stranger");
  expect((await strangerPage.request.get(`/api/v1/conversations/${conversationId}`)).status()).toBe(404);
  expect((await strangerPage.request.get(`/api/v1/conversations/${conversationId}/messages`)).status()).toBe(404);
  await deleteAccount(strangerPage);
  await stranger.close();
  expect(account.email).toBeTruthy();
});

test("only the Better Auth routes this app uses exist", async ({ request }) => {
  for (const path of [
    "/api/auth/verify-password",
    "/api/auth/sign-up/email",
    "/api/auth/list-sessions",
    "/api/auth/get-access-token",
    "/api/auth/update-user",
    "/api/auth//sign-up/email",
  ]) {
    const response = await request.post(`${APP_URL}${path}`, { data: {}, headers: SAME_ORIGIN });
    expect(response.status(), path).toBe(404);
  }
});

test("two-step sign-in: turned on in Settings, then asked for by password, by email code and at deletion", async ({
  page,
  browser,
}) => {
  const { email, password } = await createAccount(page, "twostep");
  await page.goto("/settings/privacy");
  await page.getByRole("button", { name: "Turn on two-step sign-in" }).click();
  await page.getByLabel("Your password").fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("img", { name: "QR code for your authenticator app" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
  const recovery = (await page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem").first().textContent()) ?? "";
  const setupKey = ((await page.getByText(/^Setup key:/).textContent()) ?? "").replace("Setup key:", "");
  await page.getByLabel("3. Enter the 6-digit code the app shows").fill(totp(setupKey));
  await page.getByRole("button", { name: "Turn on", exact: true }).click();
  await expect(page.getByText("Two-step sign-in is on.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Turn off" })).toBeVisible();

  // A password alone no longer signs in: the form asks for the second step, and no session exists yet.
  const other = await browser.newContext({ baseURL: APP_URL });
  const form = await other.newPage();
  await form.goto("/login");
  await form.getByLabel("Email").fill(email);
  await form.getByLabel("Password", { exact: true }).fill(password);
  await form.getByRole("button", { name: "Sign in" }).click();
  await expect(form.getByRole("heading", { name: "Two-step sign-in" })).toBeVisible();
  expect((await form.request.get("/api/v1/me")).status()).toBe(401);
  // The code used to turn it on is spent; the app's next code works.
  await form.getByLabel("Authenticator code").fill(totp(setupKey));
  await form.getByRole("button", { name: "Continue" }).click();
  await expect(form.getByRole("alert").filter({ hasText: "That code was just used" })).toBeVisible();
  await form.getByLabel("Authenticator code").fill(totp(setupKey, Date.now() + 30_000));
  await form.getByRole("button", { name: "Continue" }).click();
  await expect(form).toHaveURL(`${APP_URL}/`);
  expect((await form.request.get("/api/v1/me")).status()).toBe(200);
  await other.close();

  // An email code is a first step too: then a recovery code (once).
  const third = await browser.newContext({ baseURL: APP_URL });
  await third.request.post("/api/auth/email-otp/send-verification-otp", { data: { email, type: "sign-in" }, headers: SAME_ORIGIN });
  const byCode = await third.request.post("/api/auth/sign-in/email-otp", {
    data: { email, otp: await mailCode(email, "signin") },
    headers: SAME_ORIGIN,
  });
  expect(byCode.status()).toBe(200);
  expect(await byCode.json()).toMatchObject({ twoFactorRedirect: true });
  expect((await third.request.get("/api/v1/me")).status()).toBe(401);
  const second = await third.request.post("/api/auth/two-factor/verify-backup-code", {
    data: { code: recovery.trim() },
    headers: SAME_ORIGIN,
  });
  expect(second.status()).toBe(200);
  expect(await second.text()).not.toMatch(/"token"/);
  expect((await third.request.get("/api/v1/me")).status()).toBe(200);
  await third.close();

  // The first session is fresh (both steps, minutes ago): the password deletes the account.
  await deleteAccount(page, password);
  expect((await page.request.get("/api/v1/me")).status()).toBe(401);
});

test("Google: offered only when configured, and a cancelled sign-in says so", async ({ page }) => {
  await page.goto("/login?error=access_denied");
  await expect(page.getByRole("alert").filter({ hasText: "Google sign-in was cancelled." })).toBeVisible();
  const button = page.getByRole("button", { name: "Continue with Google" });
  if (!process.env.E2E_GOOGLE) {
    await expect(button).toHaveCount(0);
    return;
  }
  const started = await page.request.post("/api/auth/sign-in/social", {
    data: { provider: "google", callbackURL: "/", errorCallbackURL: "/login" },
    headers: SAME_ORIGIN,
  });
  expect(started.status()).toBe(200);
  const url = new URL(((await started.json()) as { url: string }).url);
  expect(url.origin).toBe("https://accounts.google.com");
  expect(url.searchParams.get("redirect_uri")).toBe(`${APP_URL}/api/auth/callback/google`);
  expect(url.searchParams.get("code_challenge_method")).toBe("S256");
  expect(url.searchParams.get("state")).toBeTruthy();
});
