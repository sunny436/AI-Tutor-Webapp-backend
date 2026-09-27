/**
 * When the app reports an active minute (POST /v1/progress/activity). The rule, also shown to
 * students under Progress & Goals: PadhAI is open and visible, and they used it (typed,
 * clicked, scrolled, touched) or a reply was streaming, within the last two minutes.
 */

export const REPORT_EVERY_MS = 60_000;
export const ACTIVE_WINDOW_MS = 2 * 60_000;

/** Fired on window after the server credited a minute, so a streak shown can refresh. */
export const ACTIVITY_EVENT = "padhai:activity";
/** Fired on window when a reply finished: the learning streak and the notifications may have changed. */
export const LEARNING_EVENT = "padhai:learning";

export function shouldReport(state: {
  visible: boolean;
  now: number;
  lastInteraction: number;
  streaming: boolean;
}): boolean {
  if (!state.visible) return false;
  return state.streaming || state.now - state.lastInteraction <= ACTIVE_WINDOW_MS;
}
