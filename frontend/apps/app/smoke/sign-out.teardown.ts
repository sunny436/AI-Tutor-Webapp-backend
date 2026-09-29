import { existsSync, rmSync } from "node:fs";

import { expect, test as teardown } from "@playwright/test";

import { CREATED, SESSION, createdChats } from "./support";

/**
 * Runs after every other project, even when they failed: deletes any chat a check could not, then
 * ends the run's session (through the page; if that fails, through the API). The saved session
 * is removed only once the server has ended it.
 */
teardown("the smoke's chats are gone and its session is ended", async ({ browser, baseURL }) => {
  if (!existsSync(SESSION)) return;
  const context = await browser.newContext({ storageState: SESSION });
  const page = await context.newPage();
  const origin = { Origin: new URL(baseURL ?? "").origin };
  try {
    for (const id of createdChats()) {
      const found = (await page.request.get(`/api/v1/conversations/${id}`)).status();
      if (found === 200) expect((await page.request.delete(`/api/v1/conversations/${id}`, { headers: origin })).status()).toBe(204);
      else expect(found, `the smoke's chat ${id}`).toBe(404);
    }
    rmSync(CREATED, { force: true });
    try {
      await page.goto("/settings/privacy");
      await page.getByRole("complementary", { name: "Settings" }).getByRole("button", { name: "Log out" }).click();
      await expect(page).toHaveURL("/login");
    } catch {
      await page.request.post("/api/v1/auth/logout", { headers: origin });
    }
    // The saved cookie itself, in a fresh context: the server must refuse it now.
    const check = await browser.newContext({ storageState: SESSION });
    const status = (await check.request.get(new URL("/api/v1/me", baseURL).toString())).status();
    await check.close();
    expect(status, "the server has ended the session").toBe(401);
    rmSync(SESSION, { force: true });
  } finally {
    await context.close();
  }
});
