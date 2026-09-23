/**
 * Wire types for the chat API.
 *
 * Mirrors the backend contract vendored at `docs/backend-openapi.v1.json`
 * (source: the backend repository's `docs/openapi.json` / `docs/api-contract.md`).
 * The backend is the source of truth; if the two disagree, this file is the bug.
 * `routes.test.ts` fails when a request type sends a field the contract does not
 * accept (the API rejects unknown fields with 422).
 */

export type Uuid = string;
/** ISO-8601 timestamp, as sent by the API. */
export type Timestamp = string;

// ---------------------------------------------------------------- accounts

export type User = {
  id: Uuid;
  email: string;
  displayName: string | null;
  emailVerified: boolean;
  createdAt: Timestamp;
};

/**
 * What the BFF returns after verify-email / login / password reset. The backend
 * also returns `session: {token, expiresAt}`; the BFF moves the token into an
 * httpOnly cookie and strips it, so the browser never sees it.
 */
export type SignedIn = { user: User };

export type SignupRequest = { email: string; password: string; displayName?: string | null };
export type VerifyEmailRequest = { email: string; code: string };
export type LoginRequest = { email: string; password: string };
export type ResendCodeRequest = { email: string; purpose?: "verify_email" | "reset_password" };
export type ForgotPasswordRequest = { email: string };
export type ResetPasswordRequest = { email: string; code: string; newPassword: string };
export type ChangePasswordRequest = { currentPassword: string; newPassword: string };
export type UpdateMeRequest = { displayName?: string | null };
export type DeleteMeRequest = { password: string };

/** The backend's password rule (auth/schemas.py): 8–128 characters, nothing else. */
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
export const DISPLAY_NAME_MAX = 80;
/** Email codes are six digits. */
export const CODE_LENGTH = 6;

// ----------------------------------------------------------- conversations

export type Conversation = {
  id: Uuid;
  title: string;
  createdAt: Timestamp;
  updatedAt: Timestamp;
};

export type ConversationPage = { items: Conversation[]; nextCursor: string | null };

export type RenameConversationRequest = { title: string };
export const TITLE_MAX = 120;

/**
 * `superseded` exists server-side (a reply replaced by regenerate) but is never
 * returned in a message list, so the UI does not model it.
 */
export type MessageStatus = "complete" | "streaming" | "cancelled" | "error";

/**
 * `system` is not returned today; it is part of the union so a future system
 * message renders as something rather than nothing.
 */
export type MessageRole = "user" | "assistant" | "system";

export type MessageMetadata = {
  model?: string;
  /** e.g. `llm_timeout`, or `interrupted` for a reply swept after a crash. */
  errorCode?: string;
  finishReason?: string;
};

export type Message = {
  id: Uuid;
  conversationId: Uuid;
  role: MessageRole;
  /** Raw Markdown exactly as the model produced it. */
  content: string;
  status: MessageStatus;
  createdAt: Timestamp;
  metadata?: MessageMetadata;
};

export type MessagePage = { items: Message[]; nextCursor: string | null };

// -------------------------------------------------------------------- chat

export type ChatRequest = { conversationId?: Uuid | null; message: string };
/** The API rejects longer messages (chat/schemas.py: 1–16,000 characters). */
export const MESSAGE_MAX = 16_000;

export type CancelResult = { status: string };

export type FeedbackRating = "up" | "down";
export type FeedbackRequest = { rating: FeedbackRating; comment?: string | null };
export type Feedback = { messageId: Uuid; rating: FeedbackRating; comment: string | null };

// ------------------------------------------------------ Server-Sent Events

/** Sent first, right after the turn is committed and before the model starts. */
export type StreamMeta = {
  conversationId: Uuid;
  conversation: Conversation;
  /** The persisted user message; `null` for a regeneration. */
  userMessage: Message | null;
  assistantMessageId: Uuid;
  /** Regeneration only: the reply this one replaces (drop it from the list). */
  replacesMessageId: Uuid | null;
};

export type StreamToken = { text: string };

/** Authoritative final state. `message.status` may be `cancelled`. */
export type StreamDone = { message: Message; conversation: Conversation };

/** Terminal failure. The partial reply is persisted with status `error`. */
export type StreamFailure = {
  code: string;
  /** Written for users by the backend; the UI still prefers its own copy per `code`. */
  message: string;
  retryable: boolean;
  messageId?: Uuid;
  requestId?: string;
};

// ------------------------------------------------------------------ errors

export type ApiErrorEnvelope = {
  error: {
    code: string;
    message?: string;
    requestId?: string;
    fields?: { field: string; reason: string }[];
  };
};
