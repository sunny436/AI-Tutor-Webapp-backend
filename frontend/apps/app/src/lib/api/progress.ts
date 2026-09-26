/** Progress (active time in PadhAI, questions, streaks) and support requests. */

import { callRoute } from "./http";
import type {
  ActivityReport,
  LearningDays,
  LearningStreak,
  NotificationList,
  Progress,
  SupportRequestIn,
  SupportRequestOut,
} from "./types";

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

/** The learning streak: the server decides it; nothing about it can be set. */
export function getStreak(): Promise<LearningStreak> {
  return callRoute("GET /v1/progress/streak");
}

/** Learning days for the calendar (the server bounds the range to a year). */
export function getLearningDays(range: { from?: string; to?: string } = {}): Promise<LearningDays> {
  return callRoute("GET /v1/progress/learning-days", { query: range });
}

/** The bell: newest first, never more than 30. */
export function getNotifications(): Promise<NotificationList> {
  return callRoute("GET /v1/notifications");
}

/** Mark notifications read: the ones given, or all of yours. */
export function markNotificationsRead(ids?: string[]): Promise<void> {
  return callRoute("POST /v1/notifications/read", { body: ids ? { ids } : {} });
}
