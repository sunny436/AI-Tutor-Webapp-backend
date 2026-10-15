/**
 * Study time, the client's part (pure, no React): what one page load observes and how it reports
 * it. The server decides every second of credit (backend app/study/service.py); this only says,
 * truthfully, whether this tab was studying since the server last heard from it.
 *
 * - **Eligible** = visible, on a learning view, online, the session running (not paused) and this
 *   tab's idle timer not idle. Nothing else, and never a UI timer.
 * - **A beat** every BEAT_EVERY_MS and at once on every change of eligibility:
 *   `wasActive` = eligible the whole time since the server's last *received* observation from this
 *   tab; `nowActive` = eligible now. The server credits only between two received observations
 *   at most 75 s apart, both active, so a lost or replayed beat can never add time.
 * - **Retry once, same beatId**, when the answer is uncertain (network, gateway); the server
 *   ignores a beat id it has seen.
 */

import { ApiError } from "@/lib/api/errors";
import type { StudyActivity, StudyBeat, StudyState } from "@/lib/api/types";

export const BEAT_EVERY_MS = 30_000;
/** The reading prompt ("Still studying?") comes this long before idle, at most. */
export const PROMPT_MAX_MS = 30_000;

/** The learning views: the tutor (`/`, `/c/<id>`) and the File Library. Everything else (Settings,
 * Help, About, Study Activity itself, previews) is never study time. */
export function isLearningView(pathname: string | null): boolean {
  const path = pathname ?? "";
  return path === "/" || path.startsWith("/c/") || path === "/library" || path.startsWith("/library/");
}

/** Reading and revision allow longer without input than practice and tests. */
export function modeOf(activity: StudyActivity): "reading" | "solving" {
  return activity === "practice" || activity === "test" ? "solving" : "reading";
}

export function idleTimeoutMs(idle: StudyState["idle"], activity: StudyActivity): number {
  return (modeOf(activity) === "reading" ? idle.readingSeconds : idle.solvingSeconds) * 1000;
}

/** Reading gets a prompt before idle (half the timeout, at most 30 s); solving goes straight to idle. */
export function promptBeforeIdleMs(timeoutMs: number, activity: StudyActivity): number {
  return modeOf(activity) === "reading" ? Math.min(PROMPT_MAX_MS, Math.floor(timeoutMs / 2)) : 0;
}

export function isEligible(facts: {
  visible: boolean;
  studyView: boolean;
  online: boolean;
  running: boolean;
  idle: boolean;
}): boolean {
  return facts.visible && facts.studyView && facts.online && facts.running && !facts.idle;
}

export type Observation = { wasActive: boolean; nowActive: boolean; rises: number };

/**
 * One tab's run of eligibility, as the server needs it. `clean` = eligible with no break since
 * the server's last received observation (a break that is still being reported keeps it true
 * until that report is sent: the edge beat closes the run).
 */
export class ActivityRun {
  private eligible: boolean;
  private clean = false;
  private rises = 0;

  constructor(eligible = false) {
    this.eligible = eligible;
  }

  get now(): boolean {
    return this.eligible;
  }

  /** Eligibility now. True when it changed: send a beat at once. */
  update(eligible: boolean): boolean {
    if (eligible === this.eligible) return false;
    if (eligible) {
      this.rises += 1;
      this.clean = false; // there was a gap since the server last heard: credit starts from the next beat
    }
    this.eligible = eligible;
    return true;
  }

  /** What to send now. */
  observe(): Observation {
    return { wasActive: this.clean, nowActive: this.eligible, rises: this.rises };
  }

  /** The server received `sent`: its reference is now that observation. */
  received(sent: Observation): void {
    // Active then, and no new run started since (so no gap): eligible ever since, or up to a drop
    // whose edge beat is still to be sent and will close the run.
    this.clean = sent.nowActive && this.rises === sent.rises;
  }

  /** The beat was lost for sure (even after its retry): the server's reference is unchanged. */
  lost(): void {
    if (!this.eligible) this.clean = false; // never claim, later, time that included this gap
  }

  /** A study action the server took as an observation: start, resume or a new context (active),
   * pause or end (not). */
  acted(active: boolean): void {
    this.clean = active && this.eligible;
  }
}

/** Uncertain: the request may or may not have reached the server. */
export function isUncertain(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return error.code === "network_error" || error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504;
}

/** Send a beat; if the answer is uncertain, once more with the SAME beat (the same beatId). */
export async function sendWithRetry(beat: StudyBeat, send: (beat: StudyBeat) => Promise<StudyState>): Promise<StudyState> {
  try {
    return await send(beat);
  } catch (error) {
    if (!isUncertain(error)) throw error;
    return send(beat);
  }
}

/** "under 1 min", "12 min", "1 h 05 min": whole minutes, rounded down once, from the server's seconds. */
export function formatStudyTime(seconds: number): string {
  if (seconds <= 0) return "0 min";
  if (seconds < 60) return "under 1 min";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

export const ACTIVITY_LABELS: Record<StudyActivity, string> = {
  reading: "Reading",
  practice: "Practice",
  revision: "Revision",
  test: "Test",
};
