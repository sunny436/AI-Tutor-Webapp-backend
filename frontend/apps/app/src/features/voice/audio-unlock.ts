/**
 * The audio voice mode plays through, made inside the student's click on the Voice button: browsers (Safari
 * above all) only let sound start from a page that created or resumed its audio in a user's gesture, and the
 * voice view loads a moment later. Tiny on purpose: it is in the composer's bundle, the rest of voice mode is not.
 */

let unlocked: AudioContext | null = null;

/** Call synchronously in the click handler. */
export function unlockAudio(): void {
  const Context = (globalThis as { AudioContext?: typeof AudioContext }).AudioContext;
  if (!Context) return;
  if (!unlocked || unlocked.state === "closed") unlocked = new Context();
  void unlocked.resume().catch(() => undefined);
}

/** The context made by `unlockAudio`, handed to one voice session (which closes it when it ends). */
export function takeUnlockedAudio(): AudioContext | null {
  const context = unlocked;
  unlocked = null;
  return context;
}

/** Whether this browser can do voice mode at all: capture, record and play. */
export function canDoVoice(): boolean {
  const scope = globalThis as { AudioContext?: unknown; MediaRecorder?: unknown; navigator?: Navigator };
  return Boolean(scope.AudioContext && scope.MediaRecorder && scope.navigator?.mediaDevices?.getUserMedia);
}
