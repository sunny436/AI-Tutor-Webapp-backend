import { chatLinks, composer, expect, expectAccessible, expectNoHorizontalOverflow, lastReply, seedTurn, test, waitForHydration } from "./support";
import { KEEP_STREAMS, fakeMicrophone, liveTracks, microphoneArgs, voiceTurns } from "./voice-fixtures";

/**
 * Voice mode (features/voice) on the e2e stack: the API's fake speech (VOICE_PROVIDER=fake: every recording is
 * heard as "What is photosynthesis?", every sentence is a tone), the fake tutor (it echoes), and Chromium's fake
 * microphone: one second of quiet, 2.4 s of speech-like sound, then long quiet, so each turn is a clean one.
 * (e2e/voice-barge-in.e2e.ts has the microphone talk over the tutor.)
 */
const MICROPHONE = fakeMicrophone("turns", 1, 2.4, 14);
test.use({ launchOptions: { args: microphoneArgs(MICROPHONE) }, permissions: ["microphone"] });

const voiceMode = (page: import("@playwright/test").Page) => page.getByRole("dialog", { name: "Voice mode" });

async function openVoice(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "Voice mode" }).click();
  const dialog = voiceMode(page);
  await expect(dialog).toBeVisible();
  return dialog;
}

test("a spoken question is heard, sent in this chat, answered and read aloud; then it listens again", async ({
  page,
  account: _,
}) => {
  await page.addInitScript(KEEP_STREAMS);
  await page.goto("/");
  await waitForHydration(page);
  await composer(page).fill("a draft kept for later");
  const dialog = await openVoice(page);
  await expect(dialog).toHaveAttribute("data-voice-state", "listening", { timeout: 10_000 });
  await expect(dialog.getByRole("status").first()).toHaveText("Listening…");

  // The microphone speaks; the tutor thinks, then speaks, then listens again.
  await expect(dialog).toHaveAttribute("data-voice-state", /transcribing|thinking|speaking/, { timeout: 15_000 });
  await expect(dialog).toHaveAttribute("data-voice-state", "speaking", { timeout: 15_000 });
  // Only the tutor: neither what was said nor the reply is written here (both are in the chat).
  await expect(dialog).not.toContainText(/photosynthesis/i);
  await expect(dialog).toHaveAttribute("data-voice-state", "listening", { timeout: 15_000 });

  // In order and measured: heard, answered, spoken.
  const [turn] = await voiceTurns(page);
  expect(turn?.transcript).toBeGreaterThan(turn?.speechEnd ?? Number.POSITIVE_INFINITY);
  expect(turn?.firstToken).toBeGreaterThanOrEqual(turn?.transcript ?? Number.POSITIVE_INFINITY);
  expect(turn?.firstAudio).toBeGreaterThan(turn?.firstSpeechRequest ?? Number.POSITIVE_INFINITY);
  console.log(
    `voice turn (fake speech, local): speech end → transcript ${Math.round((turn?.transcript ?? 0) - (turn?.speechEnd ?? 0))} ms, → first audio ${Math.round((turn?.firstAudio ?? 0) - (turn?.speechEnd ?? 0))} ms`,
  );
  // The face shows a manner, never in words.
  await expect(dialog.locator(".tutor")).toHaveAttribute("data-expression", "neutral"); // the router is off here
  await expect(dialog).not.toContainText(/neutral|explaining|encouraging|focused/);

  // Back to the chat: the turn is there as ordinary messages, the draft kept, the composer reachable.
  await dialog.getByRole("button", { name: "Back to the chat" }).click();
  await expect(voiceMode(page)).toHaveCount(0);
  await expect(page.getByRole("article", { name: "You" }).last()).toContainText("What is photosynthesis?");
  await expect(lastReply(page)).toContainText("You said: What is photosynthesis?");
  await expect(composer(page)).toBeFocused();
  await expect(composer(page)).toHaveValue("a draft kept for later");
  expect(await liveTracks(page)).toBe(0); // the microphone is off
});

test("tap the tutor to interrupt: silent at once, then listening; muted it hears nothing; End lets go of everything", async ({
  page,
  account: _,
}) => {
  await page.addInitScript(KEEP_STREAMS);
  await page.goto("/");
  await waitForHydration(page);
  const dialog = await openVoice(page);
  await expect(dialog).toHaveAttribute("data-voice-state", "speaking", { timeout: 20_000 });
  await dialog.getByRole("button", { name: "Interrupt the tutor" }).click();
  await expect(dialog).toHaveAttribute("data-voice-state", "listening");
  const turns = await voiceTurns(page);
  const interrupted = turns.find((turn) => turn.interrupted !== undefined);
  expect((interrupted?.silent ?? 1e9) - (interrupted?.interrupted ?? 0)).toBeLessThan(50); // stopped in the same task

  // Muted: the next stretch of speech is not heard.
  await dialog.getByRole("button", { name: "Microphone" }).click();
  await expect(dialog).toHaveAttribute("data-voice-state", "muted");
  await expect(dialog.getByRole("status").first()).toHaveText("Microphone off");
  const sent = await page.getByRole("article", { name: "You", includeHidden: true }).count();
  await page.waitForTimeout(18_000); // longer than the microphone's loop
  await expect(dialog).toHaveAttribute("data-voice-state", "muted");
  expect(await page.getByRole("article", { name: "You", includeHidden: true }).count()).toBe(sent);
  await dialog.getByRole("button", { name: "Microphone" }).click();
  await expect(dialog).toHaveAttribute("data-voice-state", "listening");

  await dialog.getByRole("button", { name: "End voice mode" }).click();
  await expect(voiceMode(page)).toHaveCount(0);
  expect(await liveTracks(page)).toBe(0);
});

test("no microphone permission: said plainly, with a way back; a microphone that stops ends it plainly", async ({
  page,
  account: _,
}) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
  });
  await page.goto("/");
  await waitForHydration(page);
  const denied = await openVoice(page);
  await expect(denied).toHaveAttribute("data-voice-state", "error");
  await expect(denied.getByRole("alert")).toContainText("Microphone access is blocked");
  await expect(denied.getByRole("button", { name: "Try again" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(voiceMode(page)).toHaveCount(0);
  await expect(composer(page)).toBeFocused();

  // A microphone that stops mid-session (unplugged, or the permission taken back): a fresh page (the stub
  // above stays on this one), the same signed-in student.
  const other = await page.context().newPage();
  await other.addInitScript(KEEP_STREAMS);
  await other.goto("/");
  await waitForHydration(other);
  const dialog = await openVoice(other);
  await expect(dialog).toHaveAttribute("data-voice-state", "listening", { timeout: 10_000 });
  await other.evaluate(() => {
    for (const stream of (window as unknown as { __streams: MediaStream[] }).__streams) {
      for (const track of stream.getAudioTracks()) track.dispatchEvent(new Event("ended"));
    }
  });
  await expect(dialog).toHaveAttribute("data-voice-state", "error");
  await expect(dialog.getByRole("alert")).toContainText("The microphone stopped");
  expect(await liveTracks(other)).toBe(0);
  await other.close();
});

test("opening and closing fast, going to another chat, leaving the page: no microphone is left listening", async ({
  page,
  account: _,
}) => {
  const first = await seedTurn(page, "Define osmosis");
  const second = await seedTurn(page, "Define diffusion");
  await page.addInitScript(KEEP_STREAMS);
  await page.goto(`/c/${first}`);
  await waitForHydration(page);
  for (let round = 0; round < 3; round += 1) {
    await page.getByRole("button", { name: "Voice mode" }).click();
    await expect(voiceMode(page)).toBeVisible(); // closed at once: often before the microphone is even open
    await page.keyboard.press("Escape");
    await expect(voiceMode(page)).toHaveCount(0);
  }
  await expect(voiceMode(page)).toHaveCount(0);
  await page.waitForTimeout(1500);
  expect(await liveTracks(page)).toBe(0);

  const dialog = await openVoice(page);
  await expect(dialog).toHaveAttribute("data-voice-state", "listening", { timeout: 10_000 });
  await chatLinks(page).and(page.locator(`[href='/c/${second}']`)).click();
  await expect(page).toHaveURL(new RegExp(`/c/${second}$`));
  await expect(voiceMode(page)).toHaveCount(0);
  expect(await liveTracks(page)).toBe(0);

  const again = await openVoice(page);
  await expect(again).toHaveAttribute("data-voice-state", "listening", { timeout: 10_000 });
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true })));
  await expect(voiceMode(page)).toHaveCount(0);
  expect(await liveTracks(page)).toBe(0);
});

test("dictation is unchanged, and Voice sits right of its mic", async ({ page, account: _ }) => {
  await page.addInitScript(() => {
    class Recognition {
      lang = "";
      interimResults = false;
      continuous = false;
      maxAlternatives = 1;
      onresult: ((event: unknown) => void) | null = null;
      onerror: ((event: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      start() {
        setTimeout(() => {
          const result = Object.assign([{ transcript: "photosynthesis in leaves" }], { isFinal: true });
          this.onresult?.({ resultIndex: 0, results: [result] });
          this.onend?.();
        }, 100);
      }
      stop() {}
      abort() {}
    }
    // Both names: this Chromium has the unprefixed one, which the app prefers (features/chat/dictation.ts).
    Object.assign(window, { SpeechRecognition: Recognition, webkitSpeechRecognition: Recognition });
  });
  await page.goto("/");
  await waitForHydration(page);
  await expect(page.getByRole("button", { name: "Voice mode" })).toBeVisible(); // once the API has said so
  const row = composer(page).locator("xpath=..");
  const names = await row.getByRole("button").evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-label")));
  expect(names.indexOf("Voice mode")).toBe(names.indexOf("Dictate") + 1);
  expect(names.indexOf("Send message")).toBe(names.indexOf("Voice mode") + 1);
  await page.getByRole("button", { name: "Dictate" }).click();
  await expect(composer(page)).toHaveValue("photosynthesis in leaves");
  await expect(voiceMode(page)).toHaveCount(0); // dictation never opens voice mode
});

test("the voice view is accessible and fits: 320, 768 and 1440 px, light and dark", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const width of [320, 768, 1440]) {
      await page.setViewportSize({ width, height: width < 400 ? 640 : 900 });
      const dialog = await openVoice(page);
      await expect(dialog).toHaveAttribute("data-voice-state", /listening|thinking|speaking|transcribing/, { timeout: 10_000 });
      await expectNoHorizontalOverflow(page);
      for (const name of ["Back to the chat", "Microphone", "End voice mode"]) {
        const box = await dialog.getByRole("button", { name }).boundingBox();
        expect(box && box.width >= 44 && box.height >= 44, `${name} is a 44 px target at ${width}px`).toBe(true);
      }
      await expectAccessible(page);
      await page.keyboard.press("Escape");
      await expect(voiceMode(page)).toHaveCount(0);
    }
  }
});
