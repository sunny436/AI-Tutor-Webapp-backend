/**
 * Wire types for the chat API.
 *
 * Mirrors the backend contract: `docs/openapi.json` and `docs/api-contract.md` at the
 * repository root.
 * The backend is the source of truth; if the two disagree, this file is the bug.
 * `routes.test.ts` fails when a request type sends a field the contract does not
 * accept (the API rejects unknown fields with 422).
 */

import { CONTRACT } from "./contract.gen";

export type Uuid = string;
/** ISO-8601 timestamp, as sent by the API. */
export type Timestamp = string;

// ---------------------------------------------------------------- accounts

export type Avatar = {
  /** The API path of the current photo (`/v1/me/avatar?v=<hash>`); see `avatarSrc`. */
  url: string;
};

export type User = {
  id: Uuid;
  email: string;
  displayName: string | null;
  emailVerified: boolean;
  createdAt: Timestamp;
  /** Send it back with a profile edit (versioned: another device may have changed it). */
  profileVersion: number;
  /** IANA name, e.g. "Asia/Kolkata"; null until the user confirms one. */
  timezone: string | null;
  avatar: Avatar | null;
  passwordChangedAt: Timestamp | null;
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
export type DeleteMeRequest = { password: string };

/**
 * Every Settings resource is edited the same way (docs/api-contract.md, "Versioned edits"):
 * `set` replaces the listed fields, `reset` returns fields to their defaults, `version` must be
 * the one read (else 409 `version_conflict`, whose `current` is the resource as it is now).
 */
export type VersionedEdit<Values, Field extends string> = {
  version: number;
  set?: Partial<Values>;
  reset?: Field[];
};

export type ProfileValues = { displayName: string; timezone: string };
export type UpdateProfileRequest = VersionedEdit<ProfileValues, keyof ProfileValues>;

export type SessionInfo = {
  id: Uuid;
  current: boolean;
  /** e.g. "Chrome on Windows"; never the raw user agent. */
  device: string;
  /** The network only ("203.0.113.x"), never the address. */
  ipMasked: string | null;
  createdAt: Timestamp;
  lastSeenAt: Timestamp;
  expiresAt: Timestamp;
};
export type SessionList = { items: SessionInfo[] };

export type EmailChangeRequest = { newEmail: string; password: string };
export type EmailConfirmRequest = { newEmail: string; code: string };

export type Theme = (typeof CONTRACT.AppearanceSet.theme.enum)[number];
export type FontSize = (typeof CONTRACT.AppearanceSet.fontSize.enum)[number];
export const THEMES = CONTRACT.AppearanceSet.theme.enum;
export const FONT_SIZES = CONTRACT.AppearanceSet.fontSize.enum;

export type AppearanceValues = {
  theme: Theme;
  fontSize: FontSize;
  highContrast: boolean;
  reduceMotion: boolean;
  readingComfort: boolean;
  showStreak: boolean;
};
export type Appearance = AppearanceValues & { version: number; updatedAt: Timestamp | null };

export type NotificationValues = {
  dailyReminder: boolean;
  streakWarning: boolean;
  weeklySummary: boolean;
  securityAlerts: boolean;
};
export type NotificationPreferences = NotificationValues & {
  version: number;
  /** Reminders go out only once the user has chosen a time zone. */
  remindersNeedTimezone: boolean;
  /** Whether the server sends notification emails to this user at all right now. */
  delivery: (typeof CONTRACT.NotificationPreferencesOut.delivery.enum)[number];
  updatedAt: Timestamp | null;
};

// ------------------------------------------------------------------ learning

export type CatalogEntry = { code: string; name: string; deprecated: boolean };
export type AcademicCatalog = {
  version: number;
  grades: CatalogEntry[];
  boards: CatalogEntry[];
  boardStates: CatalogEntry[];
  mediums: CatalogEntry[];
  academicYears: CatalogEntry[];
  subjects: CatalogEntry[];
};

export type MainGoal = (typeof CONTRACT.LearnerProfileSet.mainGoal.enum)[number];
export const MAIN_GOALS = CONTRACT.LearnerProfileSet.mainGoal.enum;

/** What a learner profile field holds; every field may also be unset (null, or [] for topics). */
export type LearnerProfileValues = {
  grade: string;
  board: string;
  boardState: string;
  medium: string;
  academicYear: string;
  mainGoal: MainGoal;
  targetExam: string;
  targetScorePercent: number;
  weakTopics: string[];
  dailyActiveMinutesGoal: number;
  weeklyActiveMinutesGoal: number;
  /** "HH:MM", 24-hour, in the user's time zone. */
  preferredStudyTime: string;
  shortTermGoal: string;
  longTermGoal: string;
};
export type LearnerProfileField = keyof LearnerProfileValues;
export type LearnerProfile = { [K in Exclude<LearnerProfileField, "weakTopics">]: LearnerProfileValues[K] | null } & {
  weakTopics: string[];
  version: number;
  updatedAt: Timestamp | null;
};
export type UpdateLearnerProfileRequest = VersionedEdit<LearnerProfileValues, LearnerProfileField>;

export type SubjectItem = { code: string; isPriority: boolean; needsImprovement: boolean };
export type SubjectList = { version: number; items: SubjectItem[] };

type PreferenceEnums = typeof CONTRACT.LearningPreferencesSet;
export type LearningPreferenceValues = { [K in keyof PreferenceEnums]: PreferenceEnums[K]["enum"][number] };
export type LearningPreferenceField = keyof LearningPreferenceValues;
export type LearningPreferences = LearningPreferenceValues & { version: number; updatedAt: Timestamp | null };

export type TutorPreviewRequest = {
  profile?: Partial<{ [K in LearnerProfileField]: LearnerProfileValues[K] | null }>;
  subjects?: SubjectItem[];
  preferences?: Partial<LearningPreferenceValues>;
};
export type TutorPreview = { instructions: string; maxChars: number };

export const TARGET_EXAM_MAX = CONTRACT.LearnerProfileSet.targetExam.maxLength;
export const GOAL_MAX = CONTRACT.LearnerProfileSet.shortTermGoal.maxLength;
export const TOPIC_MAX = CONTRACT.LearnerProfileSet.weakTopics.items.maxLength;
export const TOPICS_MAX = CONTRACT.LearnerProfileSet.weakTopics.maxItems;
export const DAILY_MINUTES_MAX = CONTRACT.LearnerProfileSet.dailyActiveMinutesGoal.maximum;
export const WEEKLY_MINUTES_MAX = CONTRACT.LearnerProfileSet.weeklyActiveMinutesGoal.maximum;
export const SUBJECTS_MAX = CONTRACT.ReplaceSubjectsRequest.items.maxItems;

// ------------------------------------------------------------------ progress

export type ProgressDay = { date: string; activeMinutes: number; questions: number };
export type Progress = {
  /** The time zone that decides which day is today. */
  timezone: string;
  /** True until the user chooses a time zone. */
  timezoneIsDefault: boolean;
  today: ProgressDay;
  thisWeek: { startDate: string; activeMinutes: number; questions: number };
  streak: { currentDays: number; longestDays: number };
  goals: {
    dailyActiveMinutes: number | null;
    weeklyActiveMinutes: number | null;
    dailyMet: boolean | null;
    weeklyMet: boolean | null;
  };
  /** Oldest first, including days without activity. */
  days: ProgressDay[];
};
export type ActivityReport = { credited: boolean; date: string };

// ------------------------------------------------------------------- support

export type SupportKind = (typeof CONTRACT.SupportRequestIn.kind.enum)[number];
export const SUPPORT_KINDS = CONTRACT.SupportRequestIn.kind.enum;
export type SupportRequestIn = { requestId: Uuid; kind: SupportKind; subject: string; message: string; page?: string };
export type SupportRequestOut = {
  id: Uuid;
  requestId: Uuid;
  kind: SupportKind;
  subject: string;
  status: "open" | "closed";
  createdAt: Timestamp;
};
export const SUPPORT_SUBJECT_MAX = CONTRACT.SupportRequestIn.subject.maxLength;
export const SUPPORT_MESSAGE_MIN = CONTRACT.SupportRequestIn.message.minLength;
export const SUPPORT_MESSAGE_MAX = CONTRACT.SupportRequestIn.message.maxLength;

/** The backend's password rule, from the contract (contract.gen.ts). */
export const PASSWORD_MIN = CONTRACT.SignupRequest.password.minLength;
export const PASSWORD_MAX = CONTRACT.SignupRequest.password.maxLength;
export const DISPLAY_NAME_MAX = CONTRACT.ProfileSet.displayName.maxLength;
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
export const TITLE_MAX = CONTRACT.RenameConversationRequest.title.maxLength;

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
/** The API rejects longer messages (the contract's ChatRequest.message). */
export const MESSAGE_MAX = CONTRACT.ChatRequest.message.maxLength;

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
    /** Machine-readable reasons only (`too_small`); the BFF drops anything else. */
    fields?: FieldError[];
    /** On `version_conflict`: the caller's own resource as it is now. */
    current?: unknown;
  };
};

export type FieldError = { field: string; reason?: string };
