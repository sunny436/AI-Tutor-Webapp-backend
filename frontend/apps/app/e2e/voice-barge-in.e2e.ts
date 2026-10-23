import { expect, test, waitForHydration } from "./support";
import { fakeMicrophone, microphoneArgs, voiceTurns } from "./voice-fixtures";

/**
 * Speaking over the tutor interrupts it (features/voice/vad.ts, playback mode): Chromium's fake microphone has
 * only two seconds of quiet between its stretches of speech-like sound, so the next one arrives while the tutor
 * is still reading its answer aloud. There is no echo here (the microphone is a file): this checks the detector
 * and the hand-over, not how a real room's echo behaves (that needs a real device).
 */
const MICROPHONE = fakeMicrophone("barge-in", 1, 2.4, 2);
test.use({ launchOptions: { args: microphoneArgs(MICROPHONE) }, permissions: ["microphone"] });

test("speaking over the tutor stops its speech at once, and what was said is the next turn", async ({ page, account: _ }) => {
  await page.goto("/");
  await waitForHydration(page);
  await page.getByRole("button", { name: "Voice mode" }).click();
  const dialog = page.getByRole("dialog", { name: "Voice mode" });
  await expect(dialog).toHaveAttribute("data-voice-state", "speaking", { timeout: 20_000 });
  // The microphone talks again while the tutor speaks: interrupted, then heard as a new question.
  await expect(dialog).toHaveAttribute("data-voice-state", /interrupted|transcribing/, { timeout: 15_000 });
  await expect(page.getByRole("article", { name: "You", includeHidden: true })).toHaveCount(2, { timeout: 20_000 });
  const turns = await voiceTurns(page);
  const interrupted = turns.find((turn) => turn.interrupted !== undefined);
  expect(interrupted, "a turn was interrupted by voice").toBeDefined();
  expect((interrupted?.silent ?? 1e9) - (interrupted?.interrupted ?? 0)).toBeLessThan(50);
  console.log(`barge-in: interrupt → silence ${Math.round((interrupted?.silent ?? 0) - (interrupted?.interrupted ?? 0))} ms`);
  await page.keyboard.press("Escape");
});
