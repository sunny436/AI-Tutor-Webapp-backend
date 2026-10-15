/** Study time (features/study): the server credits it; the client only reports what it observes. */

import { callRoute } from "./http";
import type { StudyBeat, StudyChapters, StudyContext, StudyState, StudySummary, Uuid } from "./types";

export function getStudyState(signal?: AbortSignal): Promise<StudyState> {
  return callRoute("GET /v1/study/session", { signal });
}

/** Starts a session, or joins the one already open on another tab or device. */
export function startStudy(clientId: Uuid, context: StudyContext): Promise<StudyState> {
  return callRoute("POST /v1/study/session", { body: { clientId, ...context } });
}

export function changeStudyContext(
  sessionId: Uuid,
  clientId: Uuid,
  expectedSegmentId: Uuid,
  context: StudyContext,
): Promise<StudyState> {
  return callRoute("PATCH /v1/study/session/{session_id}", {
    params: { session_id: sessionId },
    body: { clientId, expectedSegmentId, ...context },
  });
}

export type StudyTransition = "pause" | "resume" | "end";

const TRANSITIONS = {
  pause: "POST /v1/study/session/{session_id}/pause",
  resume: "POST /v1/study/session/{session_id}/resume",
  end: "POST /v1/study/session/{session_id}/end",
} as const;

/** 409 study_state_changed when another tab or device changed the session first. */
export function transitionStudy(
  action: StudyTransition,
  sessionId: Uuid,
  clientId: Uuid,
  expectedSegmentId: Uuid,
): Promise<StudyState> {
  return callRoute(TRANSITIONS[action], { params: { session_id: sessionId }, body: { clientId, expectedSegmentId } });
}

/** Repeating a beat (same `beatId`) changes nothing: a retry is always safe. */
export function sendStudyBeat(beat: StudyBeat): Promise<StudyState> {
  return callRoute("POST /v1/study/beat", { body: beat });
}

export function getStudySummary(days: number, signal?: AbortSignal): Promise<StudySummary> {
  return callRoute("GET /v1/study/summary", { query: { days }, signal });
}

export function getStudyChapters(subject: string, signal?: AbortSignal): Promise<StudyChapters> {
  return callRoute("GET /v1/study/chapters", { query: { subject }, signal });
}
