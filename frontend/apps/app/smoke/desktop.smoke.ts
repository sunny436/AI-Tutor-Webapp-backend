import { expect, test } from "@playwright/test";

import {
  GREETING_SHAPE,
  SLOGAN,
  badge,
  banner,
  bell,
  checklist,
  closeCelebrations,
  forceDark,
  hydrated,
  legacyColours,
  noActivityReports,
  recordCreated,
  renderedGreetingContrast,
  shot,
  sideways,
  tokenColour,
} from "./support";

/** The page after the dust settles: overlays, <body> locks, finite animations still running. */
async function settled(page: import("@playwright/test").Page) {
  await page.waitForTimeout(1000);
  return page.evaluate(() => ({
    menus: document.querySelectorAll('[role="menu"]').length,
    dialogs: document.querySelectorAll('[role="dialog"]').length,
    bodyBlocked: getComputedStyle(document.body).pointerEvents === "none",
    scrollLocked: document.body.hasAttribute("data-scroll-locked"),
    running: document
      .getAnimations()
      .filter((a) => a.playState === "running" && a.effect?.getTiming().iterations !== Number.POSITIVE_INFINITY).length,
  }));
}

test("desktop, 1280px: the chat, menus, streak, bell, branding, dark, a real question and Settings", async ({ page }) => {
  const { check, finish } = checklist("PRODUCTION SMOKE: desktop");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Nothing here reads or clears notifications (opening the bell reads nothing); both stay blocked
  // anyway, so production's data is kept as it is.
  await page.route(/\/api\/v1\/notifications\/(read|clear)$/, (route) => route.fulfill({ status: 204, body: "" }));
  await noActivityReports(page);
  await closeCelebrations(page);
  await page.goto("/");
  await hydrated(page);

  await check("header: 🔥 streak from the server, India day-end countdown, the bell", async () => {
    await expect(badge(page)).toHaveAttribute("aria-label", /^\d+ day learning streak/);
    const name = await badge(page).getAttribute("aria-label");
    await expect(banner(page).getByText(/left in today's learning day/)).toBeAttached();
    await expect(bell(page)).toBeVisible();
    const streak = await (await page.request.get("/api/v1/progress/streak")).json();
    expect(streak.timezone).toBe("Asia/Kolkata");
    expect(name).toContain(`${streak.currentStreak} day learning streak`);
    return `${name}; day ends ${streak.dayEnd}`;
  });

  await check("branding: Noto Sans, the slogan on one line in the sidebar, no 'AI Tutor India'", async () => {
    expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toMatch(/noto ?sans/i);
    const loaded = await page.evaluate(async () => {
      await document.fonts.ready;
      return [...document.fonts].filter((face) => /noto ?sans/i.test(face.family) && face.status === "loaded").length;
    });
    expect(loaded).toBeGreaterThan(0);
    const fit = await page
      .getByRole("complementary")
      .getByText(SLOGAN, { exact: true })
      .evaluate((element) => {
        const box = element.getBoundingClientRect();
        const side = element.closest("aside")?.getBoundingClientRect();
        const lines = Math.round(box.height / Number.parseFloat(getComputedStyle(element).lineHeight));
        return { lines, inside: !!side && box.right <= side.right - 12 };
      });
    expect(fit).toEqual({ lines: 1, inside: true });
    expect(await page.locator("body").innerText()).not.toMatch(/AI Tutor India/i);
  });

  await check("new chat: a study greeting word by word, header 'New chat', ONE centred composer", async () => {
    const title = page.getByRole("main").getByRole("heading", { level: 2 });
    await expect(title).toHaveText(GREETING_SHAPE);
    // textContent: WebKit's innerText drops the space where the line wraps.
    const greeting = (await title.textContent())?.replace(/\s+/g, " ").trim() ?? "";
    expect(greeting.split(" ").length).toBeGreaterThanOrEqual(3);
    expect(greeting.split(" ").length).toBeLessThanOrEqual(8);
    await expect(title.locator("[data-greeting-word]")).toHaveCount(greeting.split(" ").length);
    await expect(banner(page).getByRole("heading", { level: 1 })).toHaveText("New chat");
    await expect(page.getByText(/AI Tutor|Personal Doubts Solver|Powered by|can make mistakes/)).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Learning Hub" })).toHaveCount(0);
    // Attach files, Send, (where the browser can dictate) Dictate and (where the API offers it to this account)
    // Voice mode; nothing else.
    const voice = (await (await page.request.get("/api/v1/voice")).json()).enabled === true;
    if (voice) await expect(page.getByRole("button", { name: "Voice mode" })).toBeVisible();
    const buttons = await page.getByRole("main").getByRole("button").evaluateAll((all) => all.map((b) => b.getAttribute("aria-label")));
    expect(buttons.filter((name) => name !== "Dictate")).toEqual(
      voice ? ["Attach files", "Voice mode", "Send message"] : ["Attach files", "Send message"],
    );
    await expect(page.getByRole("textbox", { name: "Ask your doubt" })).toBeEditable();
    expect(await page.locator("form:has(textarea)").count()).toBe(1);
    const centred = await page.evaluate(() => {
      const main = (document.getElementById("main") as HTMLElement).getBoundingClientRect();
      const form = (document.querySelector("form:has(textarea)") as HTMLElement).getBoundingClientRect();
      return Math.abs(form.top + form.height / 2 - (main.top + main.height / 2)) < main.height * 0.1;
    });
    expect(centred).toBe(true);
    await shot(page, "desktop-home-light");
    return `"${greeting}"`;
  });

  await check("greeting as rendered, light: 4.5:1 or better at every point", async () => {
    const lowest = await renderedGreetingContrast(page);
    expect(lowest).toBeGreaterThanOrEqual(4.5);
    return `lowest ${lowest.toFixed(2)}:1`;
  });

  await check("account photo: it loads and draws (or the initial shows)", async () => {
    const photo = page.getByRole("complementary").getByRole("button", { name: /^Account: / }).locator("img");
    if (!(await photo.count())) return "no photo: the initial shows";
    const drawn = await photo.evaluate(async (image: HTMLImageElement) => {
      await image.decode().catch(() => undefined);
      const canvas = document.createElement("canvas");
      canvas.width = 32;
      canvas.height = 32;
      const context = canvas.getContext("2d") as CanvasRenderingContext2D;
      context.drawImage(image, 0, 0, 32, 32);
      const data = context.getImageData(0, 0, 32, 32).data;
      let light = 0;
      for (let i = 0; i < data.length; i += 4) light += ((data[i] ?? 0) + (data[i + 1] ?? 0) + (data[i + 2] ?? 0)) / 3;
      return {
        complete: image.complete,
        size: `${image.naturalWidth}×${image.naturalHeight}`,
        width: image.naturalWidth,
        brightness: Math.round(light / (data.length / 4)),
        src: image.currentSrc,
      };
    });
    expect(drawn.complete).toBe(true);
    expect(drawn.width).toBeGreaterThan(0);
    if (process.env.SMOKE_SHOTS) {
      // The uploaded photo on its own, to compare with how the sidebar draws it.
      const alone = await page.context().newPage();
      await alone.goto(drawn.src);
      await shot(alone, "account-photo-as-uploaded");
      await alone.close();
    }
    return `the uploaded photo: ${drawn.size}, mean brightness ${drawn.brightness}/255`;
  });

  await check("sidebar titles: still at rest (ellipsis, no fade); a long one slides only while hovered, right fade only", async () => {
    await page.mouse.move(900, 500);
    const rows = page.locator("nav[aria-labelledby='chats-heading'] a[href^='/c/']");
    const rest = await rows.locator(".marquee").evaluateAll((boxes) =>
      boxes.map((box) => ({
        overflowing: box.scrollWidth > box.clientWidth, // measured by the title itself only when hovered
        mask: getComputedStyle(box).maskImage || "none",
        textOverflow: getComputedStyle(box).textOverflow,
        running: (box.querySelector(".marquee-track") as HTMLElement).getAnimations().length,
      })),
    );
    for (const state of rest) expect(state).toMatchObject({ mask: "none", textOverflow: "ellipsis", running: 0 });
    const index = rest.findIndex((state) => state.overflowing);
    if (index === -1) return `${rest.length} rows, none long enough to slide`;
    const long = rows.nth(index);
    await long.hover();
    await page.waitForTimeout(700);
    const moving = await long.locator(".marquee").evaluate((box) => ({
      mask: getComputedStyle(box).maskImage,
      animation: getComputedStyle(box.querySelector(".marquee-track") as Element).animationName,
    }));
    expect(moving.animation).toBe("marquee");
    expect(moving.mask).toMatch(/^linear-gradient\((to right|90deg), rgb\(0, 0, 0\) .*rgba\(0, 0, 0, 0\)\)$/);
    await page.mouse.move(900, 500);
    await page.waitForTimeout(200);
    expect(await long.locator(".marquee-track").evaluate((track) => track.getAnimations().length)).toBe(0);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    return `${rest.length} rows, ${rest.filter((state) => state.overflowing).length} long; one slid on hover and stopped`;
  });

  await check("composer: Send is neutral while empty, brand once there is text", async () => {
    const send = page.getByRole("button", { name: "Send message" });
    await expect(send).toBeDisabled();
    expect(await send.evaluate((button) => getComputedStyle(button).backgroundColor)).toBe(await tokenColour(page, "--surface-2"));
    await page.getByRole("textbox", { name: "Ask your doubt" }).fill("x");
    await page.waitForTimeout(300);
    expect(await send.evaluate((button) => getComputedStyle(button).backgroundColor)).toBe(await tokenColour(page, "--brand"));
    await page.getByRole("textbox", { name: "Ask your doubt" }).fill("");
  });

  await check("no indigo or violet on screen, light: the chat and Settings (computed styles)", async () => {
    const paths = ["/", "/settings/profile", "/settings/appearance", "/settings/streak"];
    for (const path of paths) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await legacyColours(page), path).toEqual([]);
    }
    return paths.join(", ");
  });

  await check("dark (on this page only; the account's theme is not changed): greeting, Send, no violet", async () => {
    await page.goto("/");
    await hydrated(page);
    await forceDark(page);
    const lowest = await renderedGreetingContrast(page);
    expect(lowest).toBeGreaterThanOrEqual(4.5);
    expect(await legacyColours(page)).toEqual([]);
    const send = page.getByRole("button", { name: "Send message" });
    expect(await send.evaluate((button) => getComputedStyle(button).backgroundColor)).toBe(await tokenColour(page, "--surface-2"));
    const ground = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(ground).toBe(await tokenColour(page, "--background"));
    expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(true);
    await shot(page, "desktop-home-dark");
    await page.goto("/settings/profile");
    await hydrated(page);
    await forceDark(page);
    expect(await legacyColours(page), "/settings/profile").toEqual([]);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, "desktop-settings-dark", true);
    return `greeting lowest ${lowest.toFixed(2)}:1 on ${ground}`;
  });

  await check("a real question: dots, an even stream, named in ≤6 words everywhere, kept on reload; then deleted", async () => {
    await page.goto("/");
    await hydrated(page);
    await page.evaluate(() => {
      const watch = { dots: false, lengths: [] as number[], katex: 0 };
      Object.assign(window, { __smoke: watch });
      new MutationObserver(() => {
        const reply = [...document.querySelectorAll('article[aria-label="Assistant"]')].at(-1);
        if (!reply) return;
        if (reply.querySelector("[data-streaming-dots]")) watch.dots = true;
        const content = reply.querySelector(".message-content");
        if (content?.querySelector(".katex-error")) watch.katex += 1;
        const length = content?.textContent?.length ?? 0;
        if (length && watch.lengths.at(-1) !== length) watch.lengths.push(length);
      }).observe(document.body, { subtree: true, childList: true, characterData: true });
    });
    const listed = async () =>
      ((await (await page.request.get("/api/v1/conversations?limit=100")).json()).items as { id: string }[]).map((chat) => chat.id);
    const before = new Set(await listed());
    let id = "";
    try {
      const box = page.getByRole("textbox", { name: "Ask your doubt" });
      await box.fill("Explain photosynthesis");
      await box.press("Enter");
      await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/, { timeout: 30_000 });
      id = new URL(page.url()).pathname.split("/").pop() as string;
      // Recorded at once: the sign-out teardown deletes it if this check cannot.
      recordCreated(id);
      await expect(page.getByRole("button", { name: /^(Stop generating|Stopping)$/ })).toHaveCount(0, { timeout: 120_000 });
      await expect(page.getByRole("article", { name: "Assistant" }).last()).toHaveAttribute("aria-busy", "false");
      const watch = await page.evaluate(
        () => (window as unknown as { __smoke: { dots: boolean; lengths: number[]; katex: number } }).__smoke,
      );
      expect(watch.dots, "three dots before the words").toBe(true);
      expect(watch.lengths.length, "the reply grew in many steps").toBeGreaterThan(5);
      expect(watch.katex).toBe(0);
      // The name comes from the model, so it is checked by its shape, not its words.
      const name = banner(page).getByRole("heading", { level: 1 });
      await expect(name).not.toHaveText("New chat", { timeout: 30_000 });
      const named = (await name.innerText()).trim();
      expect(named.split(/\s+/).length, `"${named}"`).toBeLessThanOrEqual(6);
      const row = page.locator(`nav[aria-labelledby='chats-heading'] a[href='/c/${id}']`);
      await expect(row).toHaveText(named);
      await shot(page, "desktop-new-reply-light");
      await page.reload();
      await expect(name).toHaveText(named);
      await expect(row).toHaveText(named);
      // Deleted again through the sidebar, like a student: hover the row, Delete, confirm.
      const item = page.locator("nav[aria-labelledby='chats-heading'] li").filter({ has: page.locator(`a[href='/c/${id}']`) });
      await item.hover();
      await item.getByRole("button", { name: /^Delete/ }).click();
      await page.getByRole("dialog", { name: "Delete this chat?" }).getByRole("button", { name: "Delete" }).click();
      await expect(row).toHaveCount(0);
      // The sidebar removes the row at once and deletes in the background: wait for the server.
      await expect
        .poll(async () => (await page.request.get(`/api/v1/conversations/${id}`)).status(), { timeout: 15_000 })
        .toBe(404);
      return `${watch.lengths.length} visible steps; named "${named}"; deleted`;
    } finally {
      // Whatever failed above, the smoke's chat never stays on the account: found by its address,
      // or else as the chat that was not there before the question.
      const created = id ? [id] : (await listed()).filter((chat) => !before.has(chat));
      for (const chat of created) {
        recordCreated(chat);
        if ((await page.request.get(`/api/v1/conversations/${chat}`)).status() === 200) {
          const gone = await page.request.delete(`/api/v1/conversations/${chat}`, { headers: { Origin: new URL(page.url()).origin } });
          expect(gone.status(), `deleting the smoke's chat ${chat}`).toBe(204);
        }
      }
    }
  });

  await check("header theme menu: Light / Dark / System with one check (nothing changed)", async () => {
    await page.goto("/");
    await hydrated(page);
    await banner(page).getByRole("button", { name: "Colour theme" }).click();
    await expect(page.getByRole("menuitemradio")).toHaveText(["Light", "Dark", "System"]);
    expect(await page.locator('[role="menuitemradio"][aria-checked="true"]').count()).toBe(1);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
  });

  await check("sidebar: only the account; its menu has Settings and Log out", async () => {
    const side = page.getByRole("complementary");
    await expect(side.getByRole("link", { name: "Settings", exact: true })).toHaveCount(0);
    await side.getByRole("button", { name: /^Account: / }).click();
    await expect(page.getByRole("menuitem")).toHaveText(["Settings", "Log out"]);
    await shot(page, "desktop-account-menu-light");
    await page.keyboard.press("Escape");
  });

  await check("an existing chat: reply on the page (no card), neutral user bubble", async () => {
    const first = page.locator("nav[aria-labelledby='chats-heading'] a[href^='/c/']").first();
    if (!(await first.count())) return "no chats on this account to open";
    await first.click();
    await expect(page.getByRole("article", { name: "Assistant" }).first()).toBeVisible();
    const look = await page.evaluate(() => {
      const reply = document.querySelector('article[aria-label="Assistant"] div.min-w-0 > div');
      const bubble = document.querySelector('article[aria-label="You"] > div');
      return {
        replyBorder: reply ? getComputedStyle(reply).borderTopWidth : "?",
        bubble: bubble ? getComputedStyle(bubble).backgroundColor : "?",
      };
    });
    expect(look.replyBorder).toBe("0px");
    expect(look.bubble).not.toBe("rgba(0, 0, 0, 0)");
  });

  await check("bell: opens, lists at most 30 plain-text items; the API refuses more than 30", async () => {
    const list = await (await page.request.get("/api/v1/notifications")).json();
    expect(list.items.length).toBeLessThanOrEqual(30);
    expect((await page.request.get("/api/v1/notifications?limit=1000")).status()).toBe(422);
    await bell(page).click();
    await expect(page.getByRole("menu").getByText("Notifications", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    return `${list.items.length} items, ${list.unreadCount} unread (left as they were)`;
  });

  await check("motion: the tokens are live (150 / 220 / 320 ms, one easing family)", async () => {
    const tokens = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      return ["--motion-fast", "--motion-base", "--motion-slow", "--ease-standard"].map((name) => root.getPropertyValue(name).trim());
    });
    expect(tokens.slice(0, 3)).toEqual(["150ms", "220ms", "320ms"]);
    expect(tokens[3]).toMatch(/^cubic-bezier\(/);
  });

  for (const gap of [0, 50, 120]) {
    await check(`motion: [${gap}ms] bell open → close → open ends open, once; nothing stuck`, async () => {
      await bell(page).click();
      await page.waitForTimeout(gap);
      await page.keyboard.press("Escape");
      await page.waitForTimeout(gap);
      await bell(page).click();
      expect(await settled(page)).toMatchObject({ menus: 1, bodyBlocked: false, running: 0 });
      await expect(bell(page)).toHaveAttribute("aria-expanded", "true");
      await page.keyboard.press("Escape");
      expect(await settled(page)).toMatchObject({ menus: 0, running: 0 });
    });
  }

  await check("motion: sidebar collapse ↔ expand ×5 ends collapsed (5rem), then back to 18rem", async () => {
    for (let i = 0; i < 5; i += 1) {
      await page.getByRole("button", { name: /^(Collapse|Expand) sidebar$/ }).click();
      await page.waitForTimeout(50);
    }
    expect((await settled(page)).running).toBe(0);
    await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
    const width = () =>
      page
        .locator("aside > div")
        .first()
        .evaluate((element) => Math.round(element.getBoundingClientRect().width));
    // The rail is w-20 / w-72 (5rem / 18rem): in pixels that follows the account's text size.
    const rem = await page.evaluate(() => Number.parseFloat(getComputedStyle(document.documentElement).fontSize));
    const collapsed = await width();
    expect(collapsed).toBe(Math.round(5 * rem));
    await page.getByRole("button", { name: "Expand sidebar" }).click();
    await page.waitForTimeout(600);
    const expanded = await width();
    expect(expanded).toBe(Math.round(18 * rem));
    return `${collapsed}px -> ${expanded}px at ${rem}px/rem`;
  });

  await check("motion: with the system's reduced motion, menus open without moving", async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await bell(page).click();
    const reduced = await page.getByRole("menu").evaluate((menu) => Number.parseFloat(getComputedStyle(menu).animationDuration));
    expect(reduced).toBeLessThan(0.001);
    await page.keyboard.press("Escape");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await bell(page).click();
    const normal = await page.getByRole("menu").evaluate((menu) => Number.parseFloat(getComputedStyle(menu).animationDuration));
    expect(normal).toBeGreaterThan(0.1);
    await page.keyboard.press("Escape");
    return `reduced ${reduced}s, normal ${normal}s`;
  });

  await check("Study Activity: in the sidebar; the page, the header's Study button and the API (nothing started)", async () => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /^(Start a study session|.*Study session controls)$/ })).toBeVisible();
    await page.getByRole("complementary").getByRole("link", { name: "Study Activity" }).click();
    await expect(page).toHaveURL("/study");
    await expect(page.getByRole("heading", { level: 1, name: "Study Activity" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Study Activity" }).getByText("Current session")).toBeVisible();
    for (const path of ["/api/v1/study/session", "/api/v1/study/summary?days=7"]) {
      expect((await page.request.get(path)).status(), path).toBe(200);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  });

  await check("My Learning: in the sidebar; every panel loads, its six APIs answer (read only), nothing sideways at 320px", async () => {
    await page.getByRole("complementary").getByRole("link", { name: "My Learning" }).click();
    await expect(page).toHaveURL("/learning");
    await expect(page.getByRole("heading", { level: 1, name: "My Learning" })).toBeVisible();
    const region = page.getByRole("region", { name: "My Learning" });
    for (const name of ["Today's plan", "Practice by chapter", "Revision due", "Exam date", "Mastery", "Mistakes", "Recent tests"]) {
      await expect(region.getByRole("heading", { level: 2, name })).toBeVisible();
    }
    await expect(region.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 15_000 });
    await expect(region.getByRole("alert")).toHaveCount(0); // no panel failed to load
    for (const path of ["plan", "mastery", "revisions", "mistakes", "practice-tests", "practice-topics"]) {
      expect((await page.request.get(`/api/v1/progress/${path}`)).status(), path).toBe(200);
    }
    // The page scrolls in its own region, so its width is measured there as well as on the page.
    const inner = () => region.evaluate((element) => element.scrollWidth - element.clientWidth);
    for (const width of [1280, 320]) {
      await page.setViewportSize({ width, height: 800 });
      expect(await sideways(page), `${width}px`).toBeLessThanOrEqual(0);
      expect(await inner(), `${width}px, inside the page`).toBeLessThanOrEqual(0);
    }
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  await check("Settings: 13 sections; Learning & Streak with stats and calendar (one Tab stop, today in view)", async () => {
    await page.getByRole("complementary").getByRole("button", { name: /^Account: / }).click();
    await page.getByRole("menuitem", { name: "Settings" }).click();
    await expect(page).toHaveURL("/settings/profile");
    const nav = page.getByRole("navigation", { name: "Settings sections" });
    await expect(nav.getByRole("link")).toHaveCount(13);
    await nav.getByRole("link", { name: "Learning & Streak", exact: true }).click();
    await expect(page).toHaveURL("/settings/streak");
    await expect(page.locator("dt", { hasText: /^Current streak$/ })).toBeVisible();
    await expect(page.locator('svg.calendar-heatmap[role="group"]')).toBeVisible();
    await expect(page.locator('rect.day-cell[tabindex="0"]')).toHaveCount(1);
    const inView = await page.locator('rect.day-cell[tabindex="0"]').evaluate((cell) => {
      const day = cell.getBoundingClientRect();
      const view = cell.closest(".learning-calendar")?.getBoundingClientRect();
      return !!view && day.left >= view.left && day.right <= view.right;
    });
    expect(inView).toBe(true);
    expect(await page.locator(".learning-calendar").evaluate((box) => box.scrollWidth - box.clientWidth)).toBeLessThanOrEqual(0);
    await nav.getByRole("link", { name: "Notifications", exact: true }).click();
    await expect(page.getByRole("switch", { name: "Reminders in the app" })).toBeVisible();
    await nav.getByRole("link", { name: "Progress & Goals", exact: true }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Progress & Goals" })).toBeVisible();
    await nav.getByRole("link", { name: "Study Tracking", exact: true }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Study Tracking" })).toBeVisible();
    await nav.getByRole("link", { name: "Profile", exact: true }).click();
    const label = await page.getByText("Display name", { exact: true }).boundingBox();
    const input = await page.getByLabel("Display name").boundingBox();
    expect(label && input && label.x + label.width <= input.x).toBe(true);
    await nav.getByRole("link", { name: "Learning Preferences", exact: true }).click();
    await expect(page.getByRole("group", { name: "Reply language" }).getByRole("radio")).not.toHaveCount(0);
  });

  await check("a 320px window, light and dark: no sideways scroll, the header fits", async () => {
    await page.setViewportSize({ width: 320, height: 720 });
    for (const path of ["/", "/settings/streak"]) {
      await page.goto(path);
      await hydrated(page);
      await page.waitForTimeout(800);
      expect(await sideways(page), `${path} light`).toBeLessThanOrEqual(0);
      await forceDark(page);
      expect(await sideways(page), `${path} dark`).toBeLessThanOrEqual(0);
      await shot(page, `narrow-${path === "/" ? "home" : "streak"}-320-dark`, true);
    }
    await page.goto("/");
    await expect(badge(page)).toBeVisible();
    await expect(bell(page)).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  await check("motion: 320px drawer open → close → reopen (0/50/120 ms) ends open; a link closes it cleanly", async () => {
    await page.setViewportSize({ width: 320, height: 720 });
    const chats = await (await page.request.get("/api/v1/conversations")).json();
    const start = chats.items?.[0]?.id ? `/c/${chats.items[0].id}` : "/settings/profile";
    for (const gap of [0, 50, 120]) {
      await page.goto(start);
      await hydrated(page);
      const open = page.getByRole("button", { name: "Open menu" });
      await open.click();
      await page.waitForTimeout(gap);
      await page.keyboard.press("Escape");
      await page.waitForTimeout(gap);
      await open.click();
      expect(await settled(page), `gap ${gap}`).toMatchObject({ dialogs: 1, running: 0 });
      await page.getByRole("dialog", { name: "Navigation" }).getByRole("link", { name: "Ask New Doubt" }).click();
      await expect(page).toHaveURL("/");
      expect(await settled(page), `gap ${gap}`).toMatchObject({ dialogs: 0, bodyBlocked: false, scrollLocked: false, running: 0 });
    }
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  await check("files: a fresh .txt is read to Ready within 60 s, then deleted; the mic is allowed for this site", async () => {
    await page.goto("/");
    const origin = new URL(page.url()).origin;
    const policy = (await page.request.get("/")).headers()["permissions-policy"] ?? "";
    expect(policy).toContain("microphone=(self)");
    const text = `AI Tutor production smoke ${Date.now()}: photosynthesis makes food in the leaves of green plants.`;
    const created = await page.request.post(`/api/v1/files?filename=${encodeURIComponent("smoke-check.txt")}`, {
      headers: { "Content-Type": "application/octet-stream", Origin: origin },
      data: Buffer.from(text),
    });
    expect(created.status(), await created.text()).toBe(201);
    const file = (await created.json()) as { id: string };
    try {
      await expect
        .poll(async () => ((await (await page.request.get(`/api/v1/files/${file.id}`)).json()) as { status: string }).status, {
          timeout: 60_000,
          intervals: [1000],
        })
        .toBe("ready");
    } finally {
      const gone = await page.request.delete(`/api/v1/files/${file.id}`, { headers: { Origin: origin } });
      expect(gone.status()).toBe(204);
    }
    return `file ${file.id.slice(0, 8)} ready, then deleted; ${policy}`;
  });

  await check("no uncaught errors in the page", async () => {
    expect(errors).toEqual([]);
  });

  finish();
});
