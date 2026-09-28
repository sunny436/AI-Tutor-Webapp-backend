/**
 * The study greeting above a new chat's composer: this week's, from the API
 * (`GET /v1/greetings/current`, app-level, the same for everyone). The chat never depends on it:
 * whatever goes wrong (no greeting live, API down or slow, session gone), it shows FALLBACK and the
 * server logs one line saying why. Nothing is ever stored in the browser.
 */

import type { StudyGreeting } from "@/lib/api/types";
import type { BackendResult } from "@/lib/server/backend";

export const FALLBACK_GREETING = "What are you studying today?";

/** Server-side: the greeting to render, or FALLBACK with one warning line. */
export function greetingText(
  result: BackendResult<StudyGreeting>,
  warn: (line: string) => void = (line) => console.warn(line),
): string {
  if (result.status === "ok" && typeof result.data?.text === "string" && result.data.text.trim()) {
    return result.data.text;
  }
  warn(`[greeting] ${result.status === "ok" ? "malformed" : result.status}: showing the fallback`);
  return FALLBACK_GREETING;
}
