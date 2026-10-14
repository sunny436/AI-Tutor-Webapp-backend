import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";

import { type Page, expect, test } from "@playwright/test";

/**
 * Shared by the production smoke (playwright.smoke.config.ts). It signs in as the owner's account:
 * SMOKE_EMAIL and SMOKE_PASSWORD, or the first two lines of dummy_account.txt at the repository
 * root (git-ignored). Never printed.
 */
export function credentials(): { email: string; password: string } {
  const file = join(__dirname, "..", "..", "..", "..", "dummy_account.txt");
  const [email = "", password = ""] =
    process.env.SMOKE_EMAIL && process.env.SMOKE_PASSWORD
      ? [process.env.SMOKE_EMAIL, process.env.SMOKE_PASSWORD]
      : existsSync(file)
        ? readFileSync(file, "utf-8")
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter(Boolean)
        : [];
  if (!email || !password) throw new Error("set SMOKE_EMAIL and SMOKE_PASSWORD, or put them in dummy_account.txt");
  return { email, password };
}

/** The signed-in session the checks share (one sign-in per run); removed by the sign-out teardown. */
export const SESSION = join(__dirname, "..", "test-results", "smoke-session.json");
/** Chats the smoke created, so the teardown can delete any a failed check left behind. */
export const CREATED = join(__dirname, "..", "test-results", "smoke-created.json");

export function recordCreated(id: string) {
  const ids = existsSync(CREATED) ? (JSON.parse(readFileSync(CREATED, "utf-8")) as string[]) : [];
  writeFileSync(CREATED, JSON.stringify([...new Set([...ids, id])]));
}

export function createdChats(): string[] {
  return existsSync(CREATED) ? (JSON.parse(readFileSync(CREATED, "utf-8")) as string[]) : [];
}
export const SLOGAN = "Your Questions. Your Tutor. Your Way.";

/**
 * Where screenshots go, if SMOKE_SHOTS is set: an absolute folder outside the repository, since
 * they show the owner's chats, email and photo.
 */
export function shot(page: Page, name: string, fullPage = false) {
  const folder = process.env.SMOKE_SHOTS;
  if (!folder) return Promise.resolve();
  const repository = resolve(__dirname, "..", "..", "..", "..");
  const inside = !relative(repository, resolve(folder)).startsWith("..");
  if (!isAbsolute(folder) || inside) throw new Error("SMOKE_SHOTS must be an absolute folder outside the repository");
  mkdirSync(folder, { recursive: true });
  return page.screenshot({ path: join(folder, `${name}.png`), fullPage }).then(() => undefined);
}

/** Named checks that all run: one failure does not hide the rest; the test fails at the end. */
export function checklist(title: string) {
  const results: { name: string; ok: boolean; note: string }[] = [];
  return {
    async check(name: string, run: () => Promise<unknown>) {
      try {
        const note = await test.step(name, run);
        results.push({ name, ok: true, note: typeof note === "string" ? note : "" });
      } catch (error) {
        results.push({ name, ok: false, note: String((error as Error).message).split("\n").slice(0, 3).join(" | ") });
      }
    },
    finish() {
      console.log(`\n==== ${title} ====`);
      for (const { name, ok, note } of results) console.log(`${ok ? "PASS" : "FAIL"}  ${name}${note ? `  — ${note}` : ""}`);
      console.log(`==== ${results.filter((result) => result.ok).length}/${results.length} passed ====\n`);
      expect(results.filter((result) => !result.ok).map((result) => result.name)).toEqual([]);
    },
  };
}

/**
 * The app reports an active minute every minute (Progress & Goals). The smoke is not the owner
 * studying, so those reports are dropped; the app ignores a failed report.
 */
export async function noActivityReports(page: Page) {
  await page.route("**/api/v1/progress/activity", (route) => route.abort());
}

/**
 * The owner's real account may be celebrated while the smoke runs: its question can be the day's
 * first answer, and a lost streak is told when the chat opens (features/streak/celebrations). A
 * celebration is a dialog over the page, so whenever one is in the way it is closed, as a student
 * would close it.
 */
export async function closeCelebrations(page: Page) {
  await page.addLocatorHandler(page.locator("[data-celebration$='-dialog']"), async () => {
    await page.keyboard.press("Escape");
  });
}

export const hydrated = (page: Page) => page.waitForFunction(() => document.querySelector("next-route-announcer") !== null);
export const banner = (page: Page) => page.getByRole("banner");
export const badge = (page: Page) => banner(page).getByRole("link", { name: /learning streak/i });
export const bell = (page: Page) => banner(page).getByRole("button", { name: /^Notifications/ });

/** Pixels the page is wider than its window (0 or less: no sideways scroll). */
export const sideways = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/**
 * Dark on this page only: the account's theme is never changed (a smoke must not touch the owner's
 * settings). A reload brings the account's own theme back. Everything styled by the tokens turns
 * dark; the streak calendar's cells, coloured by script for next-themes' theme, stay light (its
 * dark colours are covered by the local end-to-end tests).
 */
export async function forceDark(page: Page) {
  await page.evaluate(() => {
    const html = document.documentElement;
    html.classList.remove("light");
    html.classList.add("dark");
    html.style.colorScheme = "dark";
  });
  await page.waitForTimeout(400);
}

/** A study greeting as the API accepts one (app/greetings/refresh.py): plain words, 3-8, ending in . ! or ? */
export const GREETING_SHAPE = /^[A-Z][A-Za-z0-9 ,'-]*[A-Za-z0-9][.!?]$/;

/** Visible elements painting a violet-family colour (the retired palette): must be none. */
export function legacyColours(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const colours = (value: string): number[][] =>
      [...value.matchAll(/rgba?\(([^)]+)\)|color\(srgb ([^)]+)\)/g)].map((match) => {
        if (match[1]) {
          const [r = 0, g = 0, b = 0, a = 1] = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
          return [r, g, b, a];
        }
        const [r = 0, g = 0, b = 0, a = 1] = (match[2] ?? "").split(/[\s/]+/).filter(Boolean).map(Number);
        return [r * 255, g * 255, b * 255, a];
      });
    const hsl = (r: number, g: number, b: number) => {
      const [x, y, z] = [r / 255, g / 255, b / 255];
      const max = Math.max(x, y, z);
      const min = Math.min(x, y, z);
      const l = (max + min) / 2;
      const d = max - min;
      if (!d) return [0, 0, l * 100];
      const s = d / (1 - Math.abs(2 * l - 1));
      let h = max === x ? ((y - z) / d) % 6 : max === y ? (z - x) / d + 2 : (x - y) / d + 4;
      h = (h * 60 + 360) % 360;
      return [h, s * 100, l * 100];
    };
    const found = new Set<string>();
    for (const element of document.querySelectorAll<Element>("body *")) {
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) continue;
      const style = getComputedStyle(element);
      if (style.visibility === "hidden" || Number(style.opacity) === 0) continue;
      for (const value of [style.color, style.backgroundColor, style.backgroundImage, style.boxShadow, style.fill, style.stroke]) {
        for (const [r = 0, g = 0, b = 0, a = 1] of colours(value)) {
          const [h = 0, sat = 0, l = 0] = hsl(r, g, b);
          if (a > 0.1 && sat > 20 && l > 12 && l < 92 && h >= 245 && h <= 300) {
            found.add(`${element.tagName.toLowerCase()} → ${value.slice(0, 60)}`);
          }
        }
      }
    }
    return [...found].slice(0, 10);
  });
}

/**
 * The lowest contrast anywhere in the greeting as rendered: each word painted as a solid block of
 * its gradient, against the real ground behind it (the words hidden), pixel by pixel.
 */
export async function renderedGreetingContrast(page: Page): Promise<number> {
  const heading = page.getByRole("main").getByRole("heading", { level: 2 });
  const words = heading.locator("[data-greeting-word]");
  const origin = await heading.boundingBox();
  if (!origin) throw new Error("no greeting on screen");
  const rects = await words.evaluateAll(
    (spans, at) =>
      spans.map((span) => {
        const r = span.getBoundingClientRect();
        return { x: r.left - at.x, y: r.top - at.y, width: r.width, height: r.height };
      }),
    { x: origin.x, y: origin.y },
  );
  const paint = (mode: "block" | "hidden" | "text") =>
    words.evaluateAll((spans, how) => {
      for (const span of spans as HTMLElement[]) {
        for (const property of ["background-clip", "-webkit-background-clip", "visibility"]) span.style.removeProperty(property);
        if (how === "block") {
          span.style.setProperty("background-clip", "border-box", "important");
          span.style.setProperty("-webkit-background-clip", "border-box", "important");
        }
        if (how === "hidden") span.style.setProperty("visibility", "hidden", "important");
      }
    }, mode);
  await paint("block");
  const gradient = await heading.screenshot({ animations: "disabled" });
  await paint("hidden");
  const ground = await heading.screenshot({ animations: "disabled" });
  await paint("text");
  return page.evaluate(
    async ({ gradient, ground, rects, width }) => {
      const decode = async (png: string) => {
        const image = new Image();
        image.src = `data:image/png;base64,${png}`;
        await image.decode();
        const canvas = document.createElement("canvas");
        canvas.width = image.width;
        canvas.height = image.height;
        const context = canvas.getContext("2d") as CanvasRenderingContext2D;
        context.drawImage(image, 0, 0);
        return { width: image.width, data: context.getImageData(0, 0, image.width, image.height).data };
      };
      const [fill, back] = [await decode(gradient), await decode(ground)];
      const scale = fill.width / width;
      const lum = (data: Uint8ClampedArray, i: number) =>
        [data[i] ?? 0, data[i + 1] ?? 0, data[i + 2] ?? 0]
          .map((v) => v / 255)
          .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
          .reduce((sum, c, k) => sum + c * ([0.2126, 0.7152, 0.0722][k] ?? 0), 0);
      let lowest = Number.POSITIVE_INFINITY;
      for (const rect of rects) {
        for (const at of [0.35, 0.5, 0.65]) {
          const y = Math.round((rect.y + rect.height * at) * scale);
          for (let x = Math.ceil((rect.x + 1) * scale); x < Math.floor((rect.x + rect.width - 1) * scale); x++) {
            const i = (y * fill.width + x) * 4;
            const [a, b] = [lum(fill.data, i), lum(back.data, i)];
            lowest = Math.min(lowest, (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05));
          }
        }
      }
      return lowest;
    },
    { gradient: gradient.toString("base64"), ground: ground.toString("base64"), rects, width: origin.width },
  );
}

/** The resolved colour of a design token, for comparing with a computed style. */
export function tokenColour(page: Page, token: string) {
  return page.evaluate((name) => {
    const probe = document.createElement("span");
    probe.style.backgroundColor = `hsl(var(${name}))`;
    document.body.append(probe);
    const value = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return value;
  }, token);
}
