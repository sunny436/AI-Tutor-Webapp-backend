import { createHmac } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, test as base, expect } from "@playwright/test";

import { API_URL, APP_URL, MAILPIT_URL } from "./env";

export { expect };

export const PASSWORD = "e2e-password-1";

/** `.test` is refused by the API (special-use domain); example.com is reserved for exactly this. */
let sequence = 0;
export function uniqueEmail(tag: string): string {
  sequence += 1;
  return `e2e-${tag}-${Date.now()}-${sequence}@example.com`;
}

type MailSummary = { ID: string; Subject: string };
const usedMail = new Set<string>();

/** The newest unused sign-in, reset or email-change code emailed to `email`, from Mailpit. */
export async function mailCode(email: string, purpose: "signin" | "reset" | "change"): Promise<string> {
  const subject = purpose === "reset" ? /reset/i : purpose === "change" ? /email change code/i : /sign-in code/i;
  let code: string | undefined;
  await expect
    .poll(
      async () => {
        const query = encodeURIComponent(`to:"${email}"`);
        const search = (await (await fetch(`${MAILPIT_URL}/api/v1/search?query=${query}`)).json()) as {
          messages?: MailSummary[];
        };
        // Newest first.
        const summary = search.messages?.find((message) => subject.test(message.Subject) && !usedMail.has(message.ID));
        if (!summary) return undefined;
        const message = (await (await fetch(`${MAILPIT_URL}/api/v1/message/${summary.ID}`)).json()) as { Text: string };
        code = /\b(\d{6})\b/.exec(message.Text)?.[1];
        if (code) usedMail.add(summary.ID);
        return code;
      },
      { timeout: 15_000, message: `a ${purpose} code emailed to ${email}` },
    )
    .toBeTruthy();
  return code as string;
}

/** Same-origin headers, as the browser would send them. */
export const SAME_ORIGIN = { Origin: APP_URL };

/**
 * A fresh, verified account with a password, signed in within `page`'s browser context, made the
 * way the sign-up page makes it (Better Auth, email first): a code to the address, the code (the
 * account now exists, verified), then the password. The session cookie lands in the context's jar
 * exactly as it does for a browser.
 *
 * Always through the main server (APP_URL), whose Origin these requests carry.
 * The cookie is per host, not per port, so it signs in the preview server too.
 */
export async function createAccount(page: Page, tag = "user"): Promise<{ email: string; password: string }> {
  const email = uniqueEmail(tag);
  const send = await page.request.post(`${APP_URL}/api/auth/email-otp/send-verification-otp`, {
    data: { email, type: "sign-in" },
    headers: SAME_ORIGIN,
  });
  expect(send.status(), "send a sign-in code").toBe(200);
  const otp = await mailCode(email, "signin");
  const signedIn = await page.request.post(`${APP_URL}/api/auth/sign-in/email-otp`, {
    data: { email, otp, name: "E2E" },
    headers: SAME_ORIGIN,
  });
  expect(signedIn.status(), "sign in with the code").toBe(200);
  const password = await page.request.post(`${APP_URL}/api/account/password`, {
    data: { newPassword: PASSWORD },
    headers: SAME_ORIGIN,
  });
  expect(password.status(), "set the password").toBe(204);
  return { email, password: PASSWORD };
}

/** Delete the account signed in within `page`'s context, if it still exists. */
/**
 * An authenticator app's code (RFC 6238: SHA-1, 30 seconds, 6 digits) for a base32 setup key, as
 * the app would show it at `at`. The server accepts the neighbouring periods too, so a test that
 * needs a second, different code takes the next period's.
 */
export function totp(setupKey: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...setupKey.replace(/[\s=]/g, "").toUpperCase()].map((char) => alphabet.indexOf(char).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from((bits.match(/.{8}/g) ?? []).map((byte) => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = (hmac[hmac.length - 1] ?? 0) & 0xf;
  return ((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}

export async function deleteAccount(page: Page, password = PASSWORD): Promise<void> {
  await page.request.delete(`${APP_URL}/api/v1/me`, { data: { password }, headers: SAME_ORIGIN }).catch(() => undefined);
}

type Fixtures = {
  /** Fails the test on any Content-Security-Policy violation or uncaught page error. */
  pageGuard: undefined;
  /** A signed-in throwaway account, deleted after the test. */
  account: { email: string; password: string };
};

export const test = base.extend<Fixtures>({
  pageGuard: [
    async ({ page, browserName }, use) => {
      const problems: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error" && /Content Security Policy|Refused to (load|execute|connect|apply)/i.test(message.text())) {
          problems.push(`CSP: ${message.text()}`);
        }
      });
      page.on("pageerror", (error) => {
        // WebKit reports a same-origin request cancelled by leaving the page (page.goto: Next's
        // prefetches, the streak's refresh) as "<url> due to access control checks". Every
        // request here is same-origin (the BFF), so that wording is a cancellation, not an error.
        if (browserName === "webkit" && /localhost:\d+\/\S* due to access control checks/.test(error.message)) return;
        problems.push(`Uncaught: ${error.message}`);
      });
      // Every new account's first answer starts a streak, and a streak is celebrated in a dialog
      // over the page (features/streak/celebrations): whenever one is in a test's way, close it.
      await page.addLocatorHandler(page.locator("[data-celebration$='-dialog']"), async () => {
        await page.keyboard.press("Escape");
      });
      await use(undefined);
      expect(problems, "no CSP violations or uncaught errors in the page").toEqual([]);
    },
    { auto: true },
  ],
  account: async ({ page }, use) => {
    const account = await createAccount(page);
    await use(account);
    await deleteAccount(page, account.password);
  },
});

// ------------------------------------------------------------------ the sidebar's account menu

/** Open the account menu at the foot of the sidebar (or of the phone drawer: pass it as `scope`). */
export async function accountMenu(page: Page, scope?: Locator): Promise<Locator> {
  await (scope ?? page.getByRole("complementary")).getByRole("button", { name: /^Account: / }).click();
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  return menu;
}

export async function openSettingsFromSidebar(page: Page, scope?: Locator): Promise<void> {
  await (await accountMenu(page, scope)).getByRole("menuitem", { name: "Settings" }).click();
}

export async function logOutFromSidebar(page: Page): Promise<void> {
  await (await accountMenu(page)).getByRole("menuitem", { name: "Log out" }).click();
}

// ------------------------------------------------------------------ the chat

/** The line above a new chat's composer. */
export const emptyGreeting = (page: Page) => page.getByRole("main").getByRole("heading", { level: 2 });

/** This week's study greetings, straight from the API with this page's session. */
export async function studyGreetings(page: Page): Promise<string[]> {
  // Better Auth's cookie is `<token>.<signature>`; the API takes the token.
  const cookie = (await page.context().cookies()).find((each) => each.name === "padhai_session")?.value ?? "";
  const token = decodeURIComponent(cookie).split(".")[0];
  const response = await page.request.get(`${API_URL}/v1/greetings`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status(), "GET /v1/greetings").toBe(200);
  return (await response.json()).items;
}

export const FALLBACK_GREETING = "What are you studying today?";

/** The new chat shows one of this week's greetings (the fallback when none is live); returns it. */
export async function expectStudyGreeting(page: Page): Promise<string> {
  const pool = await studyGreetings(page);
  const choices = (pool.length ? pool : [FALLBACK_GREETING]).map((text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  await expect(emptyGreeting(page)).toHaveText(new RegExp(`^(?:${choices.join("|")})$`));
  return (await emptyGreeting(page).textContent()) ?? "";
}

export const COMPOSER_NAME = "Ask your doubt";
export const composer = (page: Page) => page.getByRole("textbox", { name: COMPOSER_NAME });
export const replies = (page: Page) => page.getByRole("article", { name: "Assistant" });
export const lastReply = (page: Page) => replies(page).last();
export const stopButton = (page: Page) => page.getByRole("button", { name: "Stop generating" });

/** Type a message and send it with the Send button. */
/**
 * The page is live (React has hydrated): Next adds its route announcer then. Typing into a
 * server-rendered field before this puts text on screen that React never hears about.
 */
export async function waitForHydration(page: Page): Promise<void> {
  await page.waitForFunction(() => document.querySelector("next-route-announcer") !== null);
}

export async function send(page: Page, text: string): Promise<void> {
  await waitForHydration(page);
  await composer(page).fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

/** Wait until nothing is streaming in the chat on screen. */
export async function waitForIdle(page: Page, timeout = 30_000): Promise<void> {
  await expect(page.getByRole("button", { name: /^(Stop generating|Stopping)$/ })).toHaveCount(0, { timeout });
  await expect(lastReply(page)).toHaveAttribute("aria-busy", "false", { timeout });
}

/** Send `text` and wait for the whole reply. */
export async function sendAndWait(page: Page, text: string): Promise<void> {
  const before = await replies(page).count();
  await send(page, text);
  await expect(replies(page)).toHaveCount(before + 1);
  await waitForIdle(page);
}

/**
 * What the tutor was told about this student, as the model received it: the fake LLM answers
 * this question with the part of its system prompt the student's settings and progress added
 * (backend/app/llm/fake.py), or "No student instructions.". Asked in a new chat; the question
 * itself counts as one (a new message's prompt is read before it is counted).
 */
export async function tutorKnows(page: Page): Promise<string> {
  await page.goto("/");
  await waitForHydration(page);
  await sendAndWait(page, "[[e2e: what were you told?]]");
  return (await lastReply(page).innerText()).replace(/\s+/g, " ");
}

/** The conversation id in the URL. */
export function conversationIdOf(page: Page): string {
  const id = /\/c\/([0-9a-f-]{36})$/.exec(new URL(page.url()).pathname)?.[1];
  if (!id) throw new Error(`not on a conversation: ${page.url()}`);
  return id;
}

/**
 * One turn through the real API, exactly as the chat sends it (`{conversationId?,
 * message}`), read to the end of its stream. Returns the conversation's id. For
 * setting up state quickly — a test of the chat itself sends through the page.
 */
export async function seedTurn(page: Page, message: string, conversationId?: string): Promise<string> {
  const response = await page.request.post(`${APP_URL}/api/v1/chat/stream`, {
    data: conversationId ? { conversationId, message } : { message },
    headers: SAME_ORIGIN,
  });
  expect(response.status(), "chat/stream").toBe(200);
  const body = await response.text();
  expect(body, "the turn finished").toContain("event: done");
  const meta = body.split("\n\n").find((frame) => frame.startsWith("event: meta"));
  const id = JSON.parse(meta?.split("\ndata: ")[1] ?? "{}").conversationId as string | undefined;
  if (!id) throw new Error("no meta event in the stream");
  return id;
}

/** Rename a chat through the app's own route, as the sidebar does. */
export async function renameChat(page: Page, conversationId: string, title: string): Promise<void> {
  const response = await page.request.patch(`${APP_URL}/api/v1/conversations/${conversationId}`, {
    data: { title },
    headers: SAME_ORIGIN,
  });
  expect(response.status(), "rename").toBe(200);
}

/** The chat links in the sidebar's list. */
export const chatLinks = (page: Page) => page.locator("nav[aria-labelledby='chats-heading'] a[href^='/c/']");

/** No sideways scrolling of the page itself (wide content must scroll inside its own box). */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `horizontal overflow on ${page.url()}`).toBeLessThanOrEqual(0);
}

/** A message the fake LLM takes ~4 s to echo: long enough to stop, switch or reload mid-reply. */
export const LONG_MESSAGE = Array.from({ length: 80 }, (_, index) => `w${index + 1}`).join(" ");

// ------------------------------------------------------------ accessibility

/**
 * What the element that has focus looks like, compared with the same element
 * unfocused: a focus indicator is anything focus changes in its ring, outline or
 * border — on the element, or on the form it sits in (the composer draws its ring
 * on the form, not the textarea). Transitions are switched off while measuring,
 * or a ring caught mid-animation reads as no ring at all.
 */
export async function describeFocus(page: Page) {
  return page.evaluate(() => {
    const element = document.activeElement as HTMLElement;
    const targets = [element, element.closest("form")].filter((node): node is HTMLElement => node instanceof HTMLElement);
    const saved = targets.map((target) => target.style.getPropertyValue("transition"));
    for (const target of targets) target.style.setProperty("transition", "none", "important");
    const look = () =>
      targets
        .map((target) => {
          const style = getComputedStyle(target);
          return [style.boxShadow, style.outlineStyle, style.outlineWidth, style.outlineColor, style.borderColor].join("|");
        })
        .join("§");
    const focused = look();
    element.blur();
    const unfocused = look();
    element.focus();
    targets.forEach((target, index) => {
      if (saved[index]) target.style.setProperty("transition", saved[index]);
      else target.style.removeProperty("transition");
    });
    const box = element.getBoundingClientRect();
    return {
      label: element.getAttribute("aria-label") || element.textContent?.trim().slice(0, 40) || element.tagName,
      indicated: focused !== unfocused,
      onScreen: box.width > 0 && box.height > 0 && box.bottom > 0 && box.right > 0 && box.top < innerHeight && box.left < innerWidth,
      isComposer: element.tagName === "TEXTAREA" && element.id.startsWith("composer-"),
    };
  });
}


/** No serious or critical WCAG 2.1 A/AA violations on what is on screen now. */
export async function expectAccessible(page: Page): Promise<void> {
  // Measure the page at rest: mid-fade (the Settings workspace fades in) every colour is part
  // transparent and reads as low contrast. Endless animations (a loading pulse) are left running.
  await page
    .waitForFunction(
      () =>
        document
          .getAnimations()
          .every((animation) => animation.playState !== "running" || animation.effect?.getTiming().iterations === Number.POSITIVE_INFINITY),
      undefined,
      { timeout: 5_000 },
    )
    .catch(() => undefined);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id}: ${violation.help} — ${violation.nodes.map((node) => node.target.join(" ")).join(" | ")}`);
  expect(serious, `axe on ${page.url()}`).toEqual([]);
}
