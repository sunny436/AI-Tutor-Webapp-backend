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
 * Carries intake state only. Conversation history and the medical profile are
 * server-owned and fetched by the backend's retrieval layer. Uploaded reports
 * are NOT, any more — the backend stores nothing, so their text rides along on
 * each turn in `ConsultRequest.documents` and is held by the client.
 */
export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

/**
 * The conversation state machine. Mirrors `consult/schema.py`.
 *  idle       nothing said yet
 *  greeted    hello exchanged — the assistant must not greet again
 *  casual     chatting, no health concern raised
 *  gathering  asking about the complaint in prose, a question or two at a time
 *  asking_focus  asking which part of the plan they want
 *  completed  plan delivered
 *
 * `collecting` and `choosing` are RETIRED — they were the two card surfaces —
 * but remain in the union because conversations persisted before the change
 * still carry them. The backend maps them to `gathering` on load.
 */
export type ConsultPhase =
  | "idle"
  | "greeted"
  | "casual"
  | "gathering"
  | "asking_focus"
  | "collecting"
  | "choosing"
  | "completed";

/**
 * Phases where a typed message continues the consultation rather than starting one.
 *
 * `asking_focus` was MISSING, and the omission had a cost. At that phase the
 * backend has asked which part of the plan the reader wants; their reply is a
 * continuation, so it belongs in `freeText`. Without the phase in this list the
 * client sent it as `problem`, and the backend read it as a brand-new complaint
 * and answered with generic onboarding text.
 *
 * The backend now accepts the focus reply in either field, so this is no longer
 * load-bearing — but `freeText` is still the preferred one, and a client that
 * relies on the other side being forgiving is one release away from the bug
 * coming back.
 */
export const CONSULTING: ConsultPhase[] = [
  "gathering",
  "asking_focus",
  "collecting",
  "choosing",
];

/**
 * What the reader can ask the plan to focus on, chosen at `asking_focus`.
 *
 * `complete` is the whole six-section plan; the others narrow it. The backend
 * resolves the choice to a section set and always adds the doctor section, so a
 * narrowed plan is genuinely shorter on the wire — the client is not filtering
 * anything and must not start.
 */
export type HelpType = "root_cause" | "remedies" | "yoga" | "diet" | "complete";

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
  /**
   * What the reader asked the plan to cover.
   *
   * `help_types` is the current field and a LIST — "yoga aur diet dono" selects
   * two. `help_type` is the legacy single string, still populated, with
   * "complete" winning when present. Read the list, fall back to the string:
   * see `helpTypesOf`.
   *
   * Both are optional because a conversation persisted before they existed still
   * has to load.
   */
  help_types?: HelpType[];
  help_type?: HelpType;
  /** Detected language of the conversation. Server-owned; the UI does not set it. */
  language?: string;
  /** Symptoms gathered so far. Opaque to the UI. */
  symptoms?: string[];
  /** What the backend still wants to know. Opaque to the UI. */
  missing_info?: string[];
}

/**
 * The focus this answer was written for.
 *
 * The list wins over the legacy string, and an empty result means "no focus
 * chosen" — which is not the same as "complete", and must not be treated as it.
 */
export function helpTypesOf(
  context: ConsultContext | null | undefined,
): HelpType[] {
  if (!context) return [];
  if (context.help_types?.length) return context.help_types;
  return context.help_type ? [context.help_type] : [];
}

/**
 * `chat`  — a conversational reply (greeting, capability question, general
 *           Ayurveda question, off-topic). Plain text, no cards.
 * `error` — the assistant couldn't run at all (daily quota used up, bad key,
 *           provider down). Shown as a warning so the user waits rather than
 *           rewording their message.
 */
export type ConsultKind = "chat" | "intake" | "answer" | "escalation" | "error";

/**
 * Where an answer came from.
 *
 * `source` is the knowledge file the passage was retrieved from — `acidity.md`,
 * `hair-fall.md`. Per `backend-python/docs/knowledge-format.md` the filename IS
 * the citation, which is also why it maps cleanly onto a published URL later.
 *
 * `score` is the retrieval relevance, higher being closer. It is shown rounded
 * and only as supporting detail: a number with two decimal places invites a
 * precision the embedding does not have.
 */
export interface ConsultSource {
  section: string;
  source: string;
  score?: number | null;
}

export interface ConsultResult {
  kind: ConsultKind;
  condition: string;
  message: string;
  intake?: IntakePlan | null;
  answer: string;
  context: ConsultContext;
  sources: ConsultSource[];
  /**
   * Whether the `documents` we sent reached GraphRAG whole, or were cut.
   *
   * NOT the same flag as `UploadResult.truncated`. That one says the file was
   * too long to EXTRACT in full; this one says the text we sent this turn was
   * too long to RETRIEVE over. A report can pass the first and fail the second,
   * so both have to be readable — an answer built from the first third of a
   * blood test is still an answer, but the reader has to be told.
   *
   * Optional: a backend that predates this change omits it, and `undefined`
   * must read as "no claim", never as `false`.
   */
  documentTruncated?: boolean;
}

/**
 * One attached report as it goes over the wire.
 *
 * `filename` is the name `/api/upload` gave back, and it is not decoration: the
 * backend labels each document with it before retrieval, which is what stops
 * "your blood test shows X" being said about a value that was on a prescription.
 *
 * Deliberately just these two fields. The client's own `truncated` flag is about
 * EXTRACTION and is the client's business; the backend applies its own budget to
 * each entry and reports the outcome on the response.
 */
export interface ConsultDocument {
  filename: string;
  text: string;
}

export interface ConsultRequest {
  problem?: string;
  context?: ConsultContext | null;
  answers?: Record<string, ConsultAnswer>;
  freeText?: string;
  profile?: string;
  /**
   * Which conversation this turn belongs to — the same `sessionId` Convex keys
   * messages on and `?c=` reopens.
   *
   * Identity, not content: the backend uses it to EXCLUDE this conversation from
   * the long-term memory it retrieves. Without it, memory returned the turns of
   * the chat currently on screen, so the model was handed its own transcript a
   * second time, labelled as an earlier consultation.
   */
  conversationId?: string;
  /**
   * Every report the user has attached to THIS conversation.
   *
   * THE BACKEND NO LONGER STORES UPLOADS. `/api/upload` used to index the file
   * into a per-user vector store and return `indexed: <chunks>`; it now returns
   * the extracted `text` and keeps nothing. So the only copy is the one this
   * client is holding, and a turn that omits this field is a turn where the
   * assistant cannot see the report at all — it does not "remember" it from the
   * upload, because there is nothing to remember.
   *
   * SENT ON EVERY TURN, not only on turns that look like they are about the
   * report. The frontend cannot tell: "aur isme sugar kitna hai?" is a question
   * about an attached blood test and reads as small talk. Guessing wrong is
   * silent — the model simply answers without the document — so the guess is not
   * made.
   *
   * A LIST, and it replaced a single `documentText` string. That string had one
   * ~1,200-character retrieval budget for ALL of it, so two attachments meant
   * the second was silently dropped and the client had to make the reader pick
   * one. The backend now labels and budgets each entry itself — so send them
   * all, and do NOT pre-join them with filename headers. Joining is what the
   * list exists to replace.
   */
  documents?: ConsultDocument[];
  /**
   * Which bot this frontend is — the backend uses it to select the knowledge
   * base. Snake_case because it is the wire field the Python side reads, unlike
   * the camelCase fields above which predate that convention.
   *
   * An unregistered value is a 400. Omitting it currently falls back to the
   * default bot, which is transitional: see the note in `server.py::_resolve_bot`.
   */
  bot_id?: string;
}

/**
 * What gets persisted on an assistant row so a reopened chat can resume.
 *
 * `sources` is stored so citations survive a reload. Without it, reopening a
 * consultation showed the plan with its provenance silently missing — which is
 * worse than never showing it, because the reader has no way to tell "this
 * answer had no sources" from "the sources were dropped on the way to storage".
 *
 * `v` stays 1 on purpose. The field is OPTIONAL, so every blob written before
 * this change still validates and still resumes; `state.sources ?? []` is the
 * only reader. Bumping the version would have made `load_context` discard every
 * existing conversation — see `SUPPORTED_VERSION` in consult/state.py.
 */
export interface PersistedConsultState {
  v: 1;
  context: ConsultContext;
  intake?: IntakePlan | null;
  sources?: ConsultSource[];
  /**
   * Whether this answer was written from a truncated report.
   *
   * Persisted for the same reason `sources` is: the caveat belongs to the plan,
   * not to the tab it was first read in. The attachment itself does NOT survive
   * a reload — the backend stores nothing and the text lives in component state
   * — so without this a reopened consultation would show the plan with the
   * caveat silently dropped, which reads as a plan built from the whole report.
   *
   * Optional, and `v` stays 1: every blob written before this change still
   * validates and still resumes.
   */
  documentTruncated?: boolean;
  /**
   * The focus this answer was written for, so a reopened chat labels its
   * sections the way they were labelled when it was read. Without it, the
   * live context would relabel an old plan with whatever focus is current.
   */
  helpTypes?: HelpType[];
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
