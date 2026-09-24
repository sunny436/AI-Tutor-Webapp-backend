import type { Route } from "@playwright/test";

import { LONG_MESSAGE, composer, expect, lastReply, replies, send, sendAndWait, test, waitForIdle } from "./support";

const STREAM = "**/api/v1/chat/stream";

/**
 * Run the real request, then hand the page an edited copy of the event stream.
 * `edit` gets the frames (`: open`, `event: meta …`, tokens, `event: done …`).
 */
async function rewriteStream(route: Route, edit: (frames: string[]) => string[]): Promise<void> {
  const response = await route.fetch();
  const frames = (await response.text()).split("\n\n").filter(Boolean);
  await route.fulfill({ response, body: `${edit(frames).join("\n\n")}\n\n` });
}

test("a message that can't be sent is given back, with the reason", async ({ page, account: _ }) => {
  await page.goto("/");
  await page.route(STREAM, (route) => route.abort("internetdisconnected"));
  await send(page, "Are you there?");

  // (Scoped by text: Next's route announcer is a role="alert" too.)
  const offline = page.getByRole("alert").filter({ hasText: "You're offline" });
  await expect(offline).toBeVisible();
  await expect(composer(page)).toHaveValue("Are you there?");
  await expect(page.getByRole("article")).toHaveCount(0);

  // Back online, the same text goes through.
  await page.unroute(STREAM);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(offline).toHaveCount(0);
  await waitForIdle(page);
  await expect(lastReply(page)).toContainText("You said: Are you there?");
});

test("an error event shows the failure, and Regenerate recovers", async ({ page, account: _ }) => {
  await page.goto("/");
  await page.route(STREAM, (route) =>
    rewriteStream(route, (frames) => {
      const meta = frames.find((frame) => frame.startsWith("event: meta"));
      const { assistantMessageId } = JSON.parse(meta?.split("\ndata: ")[1] ?? "{}");
      const upTo = frames.findIndex((frame) => frame.startsWith("event: token"));
      const failure = { code: "llm_unavailable", message: "upstream down", retryable: true, messageId: assistantMessageId, requestId: "e2e" };
      // Opening frames, two tokens, then the failure instead of the rest.
      return [...frames.slice(0, upTo + 2), `event: error\ndata: ${JSON.stringify(failure)}`];
    }),
  );
  await send(page, "Tell me something");

  const failure = lastReply(page).getByRole("alert");
  await expect(failure).toContainText("The AI is unavailable");
  await expect(lastReply(page)).toContainText("You said:");

  await page.unroute(STREAM);
  await failure.getByRole("button", { name: "Regenerate" }).click();
  await expect(lastReply(page).getByRole("alert")).toHaveCount(0);
  await waitForIdle(page);
  await expect(lastReply(page)).toContainText("You said: Tell me something");
  await expect(replies(page)).toHaveCount(1);
});

test("a reply cut off without a final event is re-read, never re-sent", async ({ page, account: _ }) => {
  await page.goto("/");
  let generations = 0;
  let reads = 0;
  page.on("request", (request) => {
    if (request.method() === "GET" && /\/api\/v1\/conversations\/[^/]+\/messages/.test(request.url())) reads += 1;
  });
  await page.route(STREAM, (route) => {
    generations += 1;
    return rewriteStream(route, (frames) => frames.filter((frame) => !frame.startsWith("event: done")));
  });

  await send(page, "Please finish this sentence");
  // The server did finish the reply; after the cut the page shows what it kept.
  await expect(lastReply(page)).toContainText("You said: Please finish this sentence");
  await waitForIdle(page);
  await expect(lastReply(page).getByRole("alert")).toHaveCount(0, { timeout: 15_000 });
  expect(generations, "chat requests").toBe(1);
  expect(reads, "re-reads of the conversation").toBeGreaterThanOrEqual(1);
});

test("reloading mid-reply stops it; what was written is kept", async ({ page, account: _ }) => {
  await page.goto("/");
  await send(page, LONG_MESSAGE);
  await expect(lastReply(page)).toContainText("w5");
  await expect(page).toHaveURL(/\/c\//);

  // Closing the page closes the stream; the BFF passes that on and the API
  // cancels the reply. It can take a moment to land, so look again until it has.
  await expect(async () => {
    await page.reload();
    await expect(lastReply(page)).toContainText("Stopped", { timeout: 2_000 });
  }).toPass({ timeout: 20_000 });
  await expect(lastReply(page)).not.toContainText("w80");
  await expect(lastReply(page)).toContainText("You said: w1");
});

test("the composer refuses a message over the limit", async ({ page, account: _ }) => {
  await page.goto("/");
  await composer(page).fill("x".repeat(16_001));
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  await expect(page.getByText("16,001 / 16,000")).toBeVisible();
  await composer(page).fill("short");
  await sendAndWait(page, "short");
});
