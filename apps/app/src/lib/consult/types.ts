/**
 * Wire types for the consultation backend.
 *
 * Mirrors `backend-python/src/consult/schema.py`. Keep the two in step — the
 * Python side is the source of truth and validates/repairs everything before it
 * reaches here, so this file describes what the UI can rely on receiving.
 */

export type QuestionType = "single" | "multi" | "text";
export type QuestionDisplay = "chips" | "scale" | "cards";

export interface ConsultOption {
  id: string;
  label: string;
  emoji?: string | null;
  /** Selecting this ends the consultation with a "see a doctor" message. */
  red_flag?: boolean;
}

export interface ConsultQuestion {
  id: string;
  label: string;
  hint?: string | null;
  type: QuestionType;
  display: QuestionDisplay;
  options: ConsultOption[];
  max_select?: number | null;
  required?: boolean;
}

export interface IntakePlan {
  condition: string;
  note: string;
  questions: ConsultQuestion[];
  needs_second_round: boolean;
}

/** What the user picked for one question. Keyed by question id, so re-answering overwrites. */
export interface ConsultAnswer {
  options: string[];
  text?: string | null;
}

/**
 * Session state. Opaque to the UI apart from `phase` — it is echoed back
 * verbatim each turn and persisted so a chat can resume mid-intake.
 *
 * Carries intake state only. Conversation history, medical profile and uploaded
 * reports are server-owned and fetched by the backend's retrieval layer.
 */
export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

/**
 * The conversation state machine.
 *  idle       nothing said yet
 *  greeted    hello exchanged — the assistant must not greet again
 *  casual     chatting, no health concern raised
 *  collecting answering the generated condition questions
 *  choosing   picking which parts of the plan they want
 *  completed  plan delivered
 */
export type ConsultPhase =
  | "idle"
  | "greeted"
  | "casual"
  | "collecting"
  | "choosing"
  | "completed";

/** Phases where a typed message is extra detail, not a new message to route. */
export const CONSULTING: ConsultPhase[] = ["collecting", "choosing"];

export interface ConsultContext {
  v: number;
  phase: ConsultPhase;
  /** True once a greeting has happened, so it is never repeated. */
  greeted: boolean;
  /** Recent conversation, so replies follow on instead of restarting. */
  chat_history: ChatTurn[];
  /** The last substantial answer in full — what "explain this in English" acts on. */
  last_answer: string;
  round: number;
  problem: string;
  condition: string;
  needs_second_round: boolean;
  asked: ConsultQuestion[];
  answers: Record<string, ConsultAnswer>;
  notes: string[];
}

/**
 * `chat`  — a conversational reply (greeting, capability question, general
 *           Ayurveda question, off-topic). Plain text, no cards.
 * `error` — the assistant couldn't run at all (daily quota used up, bad key,
 *           provider down). Shown as a warning so the user waits rather than
 *           rewording their message.
 */
export type ConsultKind = "chat" | "intake" | "answer" | "escalation" | "error";

export interface ConsultResult {
  kind: ConsultKind;
  condition: string;
  message: string;
  intake?: IntakePlan | null;
  answer: string;
  context: ConsultContext;
  sources: { section: string; source: string; score?: number | null }[];
}

export interface ConsultRequest {
  problem?: string;
  context?: ConsultContext | null;
  answers?: Record<string, ConsultAnswer>;
  freeText?: string;
  profile?: string;
}

/** What gets persisted on an assistant row so a reopened chat can resume. */
export interface PersistedConsultState {
  v: 1;
  context: ConsultContext;
  intake?: IntakePlan | null;
}

export type Selection = Record<string, ConsultAnswer>;

/** True when every non-optional question has something chosen. */
export function isAnswered(question: ConsultQuestion, selection: Selection): boolean {
  const answer = selection[question.id];
  if (!answer) return false;
  return answer.options.length > 0 || Boolean(answer.text?.trim());
}

export function answeredCount(questions: ConsultQuestion[], selection: Selection): number {
  return questions.filter((q) => isAnswered(q, selection)).length;
}
