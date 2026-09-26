/** Progress (active time in PadhAI, questions, streaks) and support requests. */

import { callRoute } from "./http";
import type { ActivityReport, Progress, SupportRequestIn, SupportRequestOut } from "./types";

export function getProgress(days = 14): Promise<Progress> {
  return callRoute("GET /v1/progress", { query: { days } });
}

/** One active minute. The server credits at most one a minute across tabs and devices. */
export function reportActivity(): Promise<ActivityReport> {
  return callRoute("POST /v1/progress/activity");
}

/** Sending the same `requestId` again returns the request already made (a safe retry). */
export function sendSupportRequest(request: SupportRequestIn): Promise<SupportRequestOut> {
  return callRoute("POST /v1/support/requests", { body: request });
}

/** An unsubscribe link's token; no session needed. */
export function unsubscribe(token: string): Promise<{ kind: string; unsubscribed: boolean }> {
  return callRoute("POST /v1/notifications/unsubscribe", { body: { token } });
}
