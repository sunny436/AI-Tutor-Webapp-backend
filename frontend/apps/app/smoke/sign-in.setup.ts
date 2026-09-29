import { expect, test as setup } from "@playwright/test";

import { SESSION, SLOGAN, credentials, hydrated } from "./support";

setup("the site answers, and the owner signs in through the form", async ({ page }) => {
  const { email, password } = credentials();
  expect((await page.request.get("/login")).status()).toBe(200);
  await page.goto("/login");
  await hydrated(page);
  await expect(page.getByText(SLOGAN, { exact: true })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  try {
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL("/");
    await expect(page.locator("nav[aria-labelledby='chats-heading']")).toBeVisible();
  } finally {
    // Saved even if a check above failed, so the sign-out teardown can end this session.
    await page.context().storageState({ path: SESSION });
  }
});
