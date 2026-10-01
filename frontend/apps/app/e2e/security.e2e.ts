import { APP_URL } from "./env";
import { PASSWORD, SAME_ORIGIN, createAccount, deleteAccount, expect, test } from "./support";

test("pages are sent with the security headers", async ({ page }) => {
  const response = await page.goto("/login");
  const headers = response?.headers() ?? {};
  expect(headers["content-security-policy"]).toContain("default-src 'self'");
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(headers["content-security-policy"]).not.toContain("unsafe-eval"); // production build
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["x-powered-by"]).toBeUndefined();
});

test("signed out, a page asks to sign in; old URLs still land somewhere sensible", async ({ page }) => {
  await page.goto("/settings");
  await expect(page).toHaveURL("/login?redirect=%2Fsettings");
  await page.goto("/");
  await expect(page).toHaveURL("/login");
  // The previous app lived under /en, /fr, /es and chatted at /consult.
  await page.goto("/en/settings");
  await expect(page).toHaveURL("/login?redirect=%2Fsettings");
  await page.goto("/consult");
  await expect(page).toHaveURL("/login");
});

test("signing in never redirects to another site", async ({ page }) => {
  const { email } = await createAccount(page, "redirect");
  for (const target of ["https://evil.example/x", "//evil.example/x", "/\\evil.example/x", "/%5Cevil.example/x"]) {
    await page.request.post("/api/v1/auth/logout", { headers: SAME_ORIGIN });
    await page.goto(`/login?redirect=${encodeURIComponent(target)}`);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page, `redirect=${target}`).toHaveURL(`${APP_URL}/`);
  }
  await deleteAccount(page);
});

test("the API proxy refuses other sites, unknown routes and oversized bodies", async ({ page, account }) => {
  const crossSite = await page.request.post("/api/v1/auth/logout", { headers: { Origin: "https://evil.example" } });
  expect(crossSite.status()).toBe(403);
  expect((await page.request.get("/api/v1/me")).status(), "still signed in").toBe(200);

  expect((await page.request.get("/api/v1/admin/users")).status()).toBe(404);
  expect((await page.request.get("/api/v1/conversations/not-a-uuid")).status()).toBe(404);

  const huge = await page.request.post("/api/v1/chat/stream", {
    data: { message: "x".repeat(70_000) },
    headers: SAME_ORIGIN,
  });
  expect(huge.status()).toBe(413);

  // The browser never receives the token, even from the endpoints that issue it.
  const login = await page.request.post("/api/auth/sign-in/email", {
    data: { email: account.email, password: PASSWORD },
    headers: SAME_ORIGIN,
  });
  expect(login.status()).toBe(200);
  expect(Object.keys(await login.json()).sort()).toEqual(["redirect", "user"]);
  expect(await login.text()).not.toMatch(/token/i);
});
