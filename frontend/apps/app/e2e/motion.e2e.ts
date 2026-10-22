/**
 * The motion system, end to end: one set of tokens drives every transition; nothing animates
 * `all`; dialogs scale in place and menus grow from their trigger; a message arrives once;
 * nothing is left animating at rest; reduced motion (the OS setting or Settings) stops the
 * movement, "Jump to latest" included; and none of it shifts the layout.
 */

import { type Page, expect } from "@playwright/test";

import { composer, openSettingsFromSidebar, seedTurn, send, stopButton, test, waitForHydration, waitForIdle, LONG_MESSAGE } from "./support";

const bell = (page: Page) => page.getByRole("banner").getByRole("button", { name: /^Notifications/ });

/** Elements whose transition animates every property (not the 0s initial value). */
async function transitionsOnAll(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => {
        const style = getComputedStyle(element);
        const properties = style.transitionProperty.split(",").map((part) => part.trim());
        const durations = style.transitionDuration.split(",").map((part) => Number.parseFloat(part));
        return properties.some((property, index) => property === "all" && (durations[index] ?? durations[0] ?? 0) > 0);
      })
      .map((element) => `${element.tagName.toLowerCase()}.${String(element.className).slice(0, 60)}`),
  );
}

/** Finite animations still running. */
async function runningAnimations(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    document
      .getAnimations()
      .filter((animation) => animation.playState === "running" && animation.effect?.getTiming().iterations !== Number.POSITIVE_INFINITY)
      .map((animation) => (animation as CSSAnimation).animationName ?? "transition"),
  );
}

test("one set of tokens; nothing transitions `all`", async ({ page, account: _ }) => {
  const id = await seedTurn(page, "A reply to look at");
  await page.goto("/");
  await waitForHydration(page);
  const tokens = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return ["--motion-fast", "--motion-base", "--motion-slow", "--ease-standard", "--ease-enter", "--ease-exit"].map((name) =>
      root.getPropertyValue(name).replace(/\s+/g, ""),
    );
  });
  expect(tokens).toEqual([
    "150ms",
    "220ms",
    "320ms",
    "cubic-bezier(0.25,0.1,0.25,1)",
    "cubic-bezier(0.22,1,0.36,1)",
    "cubic-bezier(0.4,0,1,1)",
  ]);
  // A bare `transition` resolves to the tokens.
  const send = await page.getByRole("button", { name: "Send message" }).evaluate((button) => {
    const style = getComputedStyle(button);
    return [style.transitionDuration.split(",")[0]?.trim(), style.transitionTimingFunction.split("),")[0]?.trim()];
  });
  expect(send[0]).toBe("0.15s");
  expect(send[1]).toContain("cubic-bezier(0.25, 0.1, 0.25, 1");

  expect(await transitionsOnAll(page)).toEqual([]);
  await page.goto(`/c/${id}`);
  await expect(page.getByRole("article", { name: "Assistant" })).toHaveCount(1);
  expect(await transitionsOnAll(page)).toEqual([]);
  await page.goto("/settings/profile");
  await expect(page.getByRole("heading", { level: 2, name: "Profile" })).toBeVisible();
  expect(await transitionsOnAll(page)).toEqual([]);
});

test("a dialog scales in place; a menu grows from its trigger; nothing animates at rest", async ({ page, account: _ }) => {
  const id = await seedTurn(page, "A chat with a dialog to open");
  await page.goto(`/c/${id}`);
  await waitForHydration(page);

  const row = page.locator("li", { has: page.locator(`a[href="/c/${id}"]`) });
  await row.hover();
  // The dialog's centre, sampled every frame for 600 ms from the moment it appears (not from the
  // click, which a busy machine delivers late): it must not move.
  const centres = page.evaluate(
    () =>
      new Promise<number[][]>((resolve) => {
        const points: number[][] = [];
        const deadline = performance.now() + 10_000;
        let appeared = 0;
        const sample = () => {
          const now = performance.now();
          const dialog = document.querySelector('[role="dialog"]');
          if (dialog) {
            appeared ||= now;
            const box = dialog.getBoundingClientRect();
            points.push([box.left + box.width / 2, box.top + box.height / 2]);
          }
          if ((appeared && now - appeared >= 600) || now > deadline) resolve(points);
          else requestAnimationFrame(sample);
        };
        requestAnimationFrame(sample);
      }),
  );
  await row.getByRole("button", { name: /^Rename/ }).click();
  const points = await centres;
  expect(points.length, "frames sampled while the dialog opened").toBeGreaterThan(2);
  const [x0, y0] = points.at(-1) as number[];
  for (const [x, y] of points) {
    expect(Math.abs((x as number) - (x0 as number)), "no sideways drift").toBeLessThanOrEqual(1);
    expect(Math.abs((y as number) - (y0 as number)), "no vertical drift").toBeLessThanOrEqual(1);
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The bell's menu opens below the bell, aligned to its end: it grows from its top-right. Until
  // Radix has placed it, the menu waits off-screen with the default centre origin (a frame a busy
  // machine can land on), so the side and the origin are read together, in one poll, until placed.
  await bell(page).click();
  await expect
    .poll(
      () =>
        page.getByRole("menu").evaluate((menu: HTMLElement) => {
          const [x = 0, y = 0] = getComputedStyle(menu).transformOrigin.split(" ").map(Number.parseFloat);
          return { side: menu.dataset.side, fromTop: y <= 2, fromEnd: x > menu.offsetWidth / 2 };
        }),
      { message: "the bell's menu grows from its top-right" },
    )
    .toEqual({ side: "bottom", fromTop: true, fromEnd: true });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);

  await page.waitForTimeout(1_000);
  expect(await runningAnimations(page)).toEqual([]);
});

test("a message arrives once: no replay when its id is confirmed or the chat gets its address", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  await page.evaluate(() => {
    const starts: { at: string; elapsed: number }[] = [];
    (window as unknown as { __starts: typeof starts }).__starts = starts;
    document.addEventListener("animationstart", (event) => {
      const target = event.target as HTMLElement;
      if (event.animationName === "rise-in" && target.tagName === "ARTICLE") {
        starts.push({ at: target.getAttribute("aria-label") ?? "", elapsed: event.elapsedTime });
      }
    });
  });
  await send(page, "Explain evaporation in one line");
  await waitForIdle(page);
  await expect(page).toHaveURL(/\/c\//);
  const starts = await page.evaluate(() => (window as unknown as { __starts: { at: string; elapsed: number }[] }).__starts);
  // Continuations of an arrival already under way start part-way (elapsed > 0); a fresh
  // arrival starts at 0. The reply arrives fresh exactly once. The student's message arrives
  // once too: fresh as it is sent, or, when the server confirms it before its first frame (a busy
  // machine), only as the continuation; never a second fresh start (a replay).
  const fresh = (label: string) => starts.filter((start) => start.at === label && start.elapsed === 0).length;
  expect(fresh("Assistant"), "the reply's arrival").toBe(1);
  expect(fresh("You"), "the student's message never replays").toBeLessThanOrEqual(1);
  expect(starts.filter((start) => start.at === "You").length, "the student's message arrives").toBeGreaterThan(0);
  // A new account's first answer starts its streak, and the "Started" celebration plays (finite, on
  // purpose) once the chat is still: close it, then nothing may be left animating.
  const celebration = page.locator("[data-celebration$='-dialog']");
  if (await celebration.waitFor({ timeout: 10_000 }).then(() => true, () => false)) await page.keyboard.press("Escape");
  await expect(celebration).toHaveCount(0);
  await page.waitForTimeout(1_000);
  expect(await runningAnimations(page)).toEqual([]);
});

test("reduced motion, from the OS or from Settings: no movement, and Jump to latest lands at once", async ({ page, account: _ }) => {
  test.setTimeout(120_000);
  let id = "";
  for (let turn = 0; turn < 12; turn += 1) id = await seedTurn(page, `Question ${turn + 1}: how do plants, animals and people use water?`, id || undefined);

  for (const mode of ["os", "settings"] as const) {
    await page.emulateMedia({ reducedMotion: mode === "os" ? "reduce" : "no-preference" });
    await page.goto(`/c/${id}`);
    await waitForHydration(page);
    // The chat opens at its latest message once the messages are in: scroll after that.
    await expect(page.getByRole("article", { name: "Assistant" })).toHaveCount(12);
    if (mode === "settings") await page.evaluate(() => document.documentElement.setAttribute("data-motion", "reduce"));

    await bell(page).click();
    const menu = await page.getByRole("menu").evaluate((element) => {
      const style = getComputedStyle(element);
      return { duration: Number.parseFloat(style.animationDuration), transform: style.transform };
    });
    expect(menu.duration, `${mode}: the menu does not animate`).toBeLessThan(0.001);
    expect(["none", "matrix(1, 0, 0, 1, 0, 0)"], `${mode}: and is not scaled`).toContain(menu.transform);
    await page.keyboard.press("Escape");

    const transcript = page.locator("main .overflow-y-auto").first();
    await transcript.evaluate((element) => element.scrollTo({ top: 0 }));
    await page.getByRole("button", { name: "Jump to latest" }).click();
    const gap = await transcript.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop);
    expect(gap, `${mode}: jumped straight to the end`).toBeLessThanOrEqual(2);
  }
});

test("sending, streaming, menus and Settings shift nothing on the page", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  // Typed text growing the composer is the reader's own doing (a keypress excludes it from the
  // metric); Playwright's fill() has no keypress, so it is filled before measuring, and the page is
  // left to settle around it (the greeting's arrival ends, the grown composer is laid out).
  await composer(page).fill(LONG_MESSAGE);
  await page.evaluate(async () => {
    const finite = document
      .getAnimations()
      .filter((animation) => animation.playState === "running" && animation.effect?.getTiming().iterations !== Number.POSITIVE_INFINITY);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  await page.evaluate(() => {
    type Shift = PerformanceEntry & {
      value: number;
      hadRecentInput: boolean;
      sources: { node: Node | null; previousRect: DOMRectReadOnly; currentRect: DOMRectReadOnly }[];
    };
    const shifts: { value: number; what: string }[] = [];
    (window as unknown as { __shifts: typeof shifts }).__shifts = shifts;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as Shift[]) {
        if (entry.hadRecentInput) continue;
        const what = entry.sources
          .map((source) => {
            const node = source.node as Element | null;
            const name = node ? `${node.nodeName.toLowerCase()}.${String((node as Element).className ?? "").slice(0, 50)}` : "?";
            return `${name} y ${Math.round(source.previousRect.y)}->${Math.round(source.currentRect.y)} h ${Math.round(source.previousRect.height)}->${Math.round(source.currentRect.height)} @${location.pathname}`;
          })
          .join(" | ");
        shifts.push({ value: entry.value, what });
      }
    }).observe({ type: "layout-shift", buffered: false });
  });
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(stopButton(page)).toBeVisible();
  await page.waitForTimeout(800);
  await bell(page).click();
  await page.keyboard.press("Escape");
  await stopButton(page).click();
  await waitForIdle(page);
  await openSettingsFromSidebar(page);
  const nav = page.getByRole("navigation", { name: "Settings sections" });
  for (const name of ["Notifications", "Learning & Streak", "Appearance & Accessibility"]) {
    await nav.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 2, name, exact: true })).toBeVisible();
  }
  const shifts = await page.evaluate(() => (window as unknown as { __shifts: { value: number; what: string }[] }).__shifts);
  const cls = shifts.reduce((sum, shift) => sum + shift.value, 0);
  expect(cls, `cumulative layout shift: ${JSON.stringify(shifts)}`).toBeLessThan(0.01);
});
