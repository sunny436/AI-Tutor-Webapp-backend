/**
 * The ONLY file that knows the central API's wire format.
 *
 * Everything else in the app speaks `ConsultResult` from `./types`, which is the
 * contract the consult page, the card renderer and `answer-sections.tsx` are
 * built on. Keeping the translation in one place is what lets the whole UI stay
 * untouched by this migration — and what makes their format changing a one-file
 * edit rather than a hunt.
 *
 * SERVER ONLY. It reads the API key, so importing it from a client component
 * would ship the key to the browser. It is imported by
 * `app/api/consult/route.ts` and nothing else.
 *
 * WHAT IS CONFIRMED AND WHAT IS NOT
 * The three request fields below — `user_id`, `application_id`, `prompt_id` —
 * are the ones you specified, so the request side is written to that. The
 * RESPONSE shape has not been supplied yet, so `normalizeCentralResponse` is
 * written as a tolerant reader rather than a guess dressed up as a fact: it
 * accepts the handful of shapes such an API realistically returns, and when it
 * recognises none of them it throws an error naming the keys it actually
 * received. Filling in the real mapping is then a single glance at that message
 * instead of a debugging session.
 */

import type {
  ConsultAnswer,
  ConsultContext,
  ConsultKind,
  ConsultQuestion,
  ConsultResult,
  IntakePlan,
} from "./types";

export const centralConfig = {
  url: process.env.CENTRAL_API_URL ?? "",
  applicationId: process.env.CENTRAL_APPLICATION_ID ?? "",
  promptId: process.env.CENTRAL_PROMPT_ID ?? "",
  // Server-only on purpose: no NEXT_PUBLIC_ prefix, so Next.js will not inline
  // it into the client bundle.
  apiKey: process.env.CENTRAL_API_KEY ?? "",
};

export function centralConfigProblem(): string {
  const missing = (
    [
      ["CENTRAL_API_URL", centralConfig.url],
      ["CENTRAL_APPLICATION_ID", centralConfig.applicationId],
      ["CENTRAL_PROMPT_ID", centralConfig.promptId],
      ["CENTRAL_API_KEY", centralConfig.apiKey],
    ] as const
  )
    .filter(([, value]) => !value)
    .map(([name]) => name);
  return missing.length ? `not configured: ${missing.join(", ")}` : "";
}

/** Who the request is for. Resolved server-side from the session, never trusted from the body. */
export type Principal = {
  /** Convex user id — stable, never changes. */
  userId: string;
  email: string;
  phone: string;
};

export type CentralTurn = {
  principal: Principal;
  /** What the user typed, when they typed outside an open consultation. */
  message: string;
  /** Extra text typed while cards are on screen. */
  freeText: string;
  /** Card selections, keyed by question id. */
  answers: Record<string, ConsultAnswer>;
  /** Groups the turns of one conversation. */
  conversationId: string;
  /** Session state echoed back, while we still keep it client-side. */
  context: ConsultContext | null;
};

export function buildCentralRequest(turn: CentralTurn): Record<string, unknown> {
  return {
    // You specified user_id as "the user's email or phone". Both are sent, plus
    // the Convex id, because email is MUTABLE: if the central API keys history
    // on an address, changing it silently orphans every past consultation.
    // Sending the stable id alongside costs nothing and leaves that fixable
    // without another migration.
    user_id: turn.principal.email || turn.principal.phone || turn.principal.userId,
    user_email: turn.principal.email || undefined,
    user_phone: turn.principal.phone || undefined,
    user_ref: turn.principal.userId,

    application_id: centralConfig.applicationId,
    prompt_id: centralConfig.promptId,

    conversation_id: turn.conversationId || undefined,
    message: turn.message || turn.freeText || "",
    answers: Object.keys(turn.answers).length ? turn.answers : undefined,
    context: turn.context ?? undefined,
  };
}

// ---------------------------------------------------------------------------
// Reading the reply
// ---------------------------------------------------------------------------

const KINDS: ConsultKind[] = ["chat", "intake", "answer", "escalation", "error"];

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function firstString(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

/** Pull the question list out of whatever it is nested under. */
function findQuestions(body: Record<string, unknown>): ConsultQuestion[] | null {
  const candidates: unknown[] = [
    asRecord(body.intake)?.questions,
    body.questions,
    body.cards,
    asRecord(body.form)?.questions,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length) {
      return candidate as ConsultQuestion[];
    }
  }
  return null;
}

/**
 * Turn the central API's reply into the `ConsultResult` the UI renders.
 *
 * `fallbackContext` is echoed back when the response carries no context of its
 * own, so a conversation that is mid-intake is not reset by a reply that simply
 * did not mention state.
 */
export function normalizeCentralResponse(
  raw: unknown,
  fallbackContext: ConsultContext | null,
): ConsultResult {
  const outer = asRecord(raw);
  if (!outer) {
    throw new Error(`central API returned ${typeof raw}, expected an object`);
  }
  // Many gateways wrap the payload. Unwrap one level before giving up.
  const body = asRecord(outer.data) ?? asRecord(outer.result) ?? outer;

  const questions = findQuestions(body);
  const text = firstString(body, [
    "answer",
    "message",
    "reply",
    "text",
    "response",
    "content",
    "output",
  ]);

  if (!questions && !text) {
    // Deliberately loud. A silent empty bubble is the worst outcome here: it
    // looks like the assistant said nothing rather than like a mapping that
    // needs one line changed.
    throw new Error(
      `central API reply not understood. Top-level keys: [${Object.keys(body).join(", ")}]. Add the mapping in normalizeCentralResponse (lib/consult/central.ts).`,
    );
  }

  const declaredKind = firstString(body, ["kind", "type", "status"]).toLowerCase();
  const kind: ConsultKind = KINDS.includes(declaredKind as ConsultKind)
    ? (declaredKind as ConsultKind)
    : questions
      ? "intake"
      : "chat";

  const intake: IntakePlan | null = questions
    ? {
        condition: firstString(body, ["condition"]),
        note: firstString(asRecord(body.intake) ?? body, ["note", "title"]),
        questions,
        needs_second_round: Boolean(
          (asRecord(body.intake) ?? body).needs_second_round,
        ),
      }
    : null;

  const context =
    (asRecord(body.context) as unknown as ConsultContext | null) ?? fallbackContext;

  return {
    kind,
    condition: firstString(body, ["condition"]),
    message: text,
    intake,
    answer: text,
    // The UI echoes this back next turn. `as` is safe here because the value is
    // opaque to us either way — it is the server's own state, not something the
    // UI reads beyond `phase`.
    context: (context ?? {}) as ConsultContext,
    sources: Array.isArray(body.sources)
      ? (body.sources as ConsultResult["sources"])
      : [],
  };
}
