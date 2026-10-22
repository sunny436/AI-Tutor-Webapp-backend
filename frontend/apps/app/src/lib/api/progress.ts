/** Progress (active time in PadhAI, questions, streaks, practice) and support requests. */

import { callRoute } from "./http";
import type {
  ActivityReport,
  LearningDays,
  LearningStreak,
  Mastery,
  Mistakes,
  NotificationList,
  PracticePlan,
  PracticeTests,
  PracticeTopics,
  Progress,
  Revisions,
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

// My Learning: the student's own record from question-bank tests in the chat, derived on every read.

/** Today's plan: at most six tasks, the same all day. */
export function getPracticePlan(signal?: AbortSignal): Promise<PracticePlan> {
  return callRoute("GET /v1/progress/plan", { signal });
}

export function getMastery(signal?: AbortSignal): Promise<Mastery> {
  return callRoute("GET /v1/progress/mastery", { signal });
}

export function getRevisions(signal?: AbortSignal): Promise<Revisions> {
  return callRoute("GET /v1/progress/revisions", { signal });
}

/** Wrong answers grouped by concept (the server allows 1 to 200). */
export function getMistakes(limit = 50, signal?: AbortSignal): Promise<Mistakes> {
  return callRoute("GET /v1/progress/mistakes", { query: { limit }, signal });
}

/** Recent question-bank tests, newest first (the server allows 1 to 100). */
export function getPracticeTests(limit = 20, signal?: AbortSignal): Promise<PracticeTests> {
  return callRoute("GET /v1/progress/practice-tests", { query: { limit }, signal });
}

/** The chapters and topics the bank can test the student on (their class and medium). */
export function getPracticeTopics(signal?: AbortSignal): Promise<PracticeTopics> {
  return callRoute("GET /v1/progress/practice-topics", { signal });
}

/** The bell: newest first, never more than 30. */
export function getNotifications(): Promise<NotificationList> {
  return callRoute("GET /v1/notifications");
}

/** Mark notifications read: the ones given, or all of yours (also those beyond the 30 listed). */
export function markNotificationsRead(ids?: string[]): Promise<void> {
  return callRoute("POST /v1/notifications/read", { body: ids ? { ids } : {} });
}

/** Clear the bell: every notification of yours leaves the list and counts as read. */
export function clearNotifications(): Promise<void> {
  return callRoute("POST /v1/notifications/clear");
}
