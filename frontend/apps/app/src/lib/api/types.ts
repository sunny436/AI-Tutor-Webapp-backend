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

/** Re-authentication: the password, or none for an account without one (Google only), which
 * must then have signed in within 15 minutes (else 409 `reauth_required`). */
export type DeleteMeRequest = { password?: string };

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

/** `password` is left out for an account without one: it must have signed in within 15 minutes. */
export type EmailChangeRequest = { newEmail: string; password?: string };
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

/** This week's study greetings (`GET /v1/greetings`): app-level, the same pool for every user. */
export type StudyGreetingPool = { weekOf: string; items: string[] };

export type NotificationValues = {
  dailyReminder: boolean;
  streakWarning: boolean;
  weeklySummary: boolean;
  securityAlerts: boolean;
  /** Reminders in the app's notifications (streak, daily, weekly). */
  inAppReminders: boolean;
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
  /** "YYYY-MM-DD": the next exam, from today to two years ahead (My Learning's plan counts down to it). */
  examDate: string;
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
/** The furthest exam date the API accepts, in days from today (the contract has no limit for dates). */
export const EXAM_DATE_MAX_DAYS = 730;
export const SUBJECTS_MAX = CONTRACT.ReplaceSubjectsRequest.items.maxItems;

// ------------------------------------------------------------------ progress

export type ProgressDay = { date: string; activeMinutes: number; questions: number };

/** The learning streak (GET /v1/progress/streak): computed by the server, India days. */
export type LearningStreak = {
  currentStreak: number;
  longestStreak: number;
  /** Today already has learning; false means today is still pending. */
  todayActive: boolean;
  todayDate: string;
  timezone: string;
  /** When today's learning day ends (UTC instant). */
  dayEnd: Timestamp;
  /** The streak that ended, once `currentStreak` is 0 after a whole missed India day; else 0. */
  previousStreak: number;
  /** The latest learning day (India date); null before the first. */
  lastLearningDate: string | null;
};
export type LearningDay = { date: string; interactions: number; intensity: number };
export type LearningDays = { start: string; end: string; days: LearningDay[] };

export type AppNotification = {
  id: Uuid;
  kind: string;
  /** Plain text: never rendered as HTML. */
  title: string;
  body: string;
  link: string | null;
  createdAt: Timestamp;
  readAt: Timestamp | null;
};
export type NotificationList = { items: AppNotification[]; unreadCount: number };
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

// ------------------------------------------------------- practice (My Learning)
//
// The student's own record from question-bank tests in the chat, derived by the server on every
// read (GET /v1/progress/plan, mastery, revisions, mistakes, practice-tests, practice-topics).
// Estimates are the server's; dates are India learning days ("YYYY-MM-DD"). The unions below are
// the backend's Literals, restated until `bun run contract` generates them.

export type PracticeLanguage = "english" | "hindi" | "sanskrit";
export type MasteryState = "mastered" | "learning" | "weak" | "not_enough_evidence";
export type OptionLetter = "A" | "B" | "C" | "D";

export type PlanTask = {
  kind: "revise" | "strengthen" | "learn";
  reason: "overdue" | "due" | "weak_concept" | "next_topic" | "start_here";
  subjectCode: string;
  classLevel: number;
  language: PracticeLanguage;
  bookTitle: string;
  chapterId: string;
  chapterNumber: number;
  chapterTitle: string;
  topicId: string;
  topicNumber: number;
  topicTitle: string;
  conceptTag: string | null;
  estimate: number | null;
  dueDate: string | null;
  overdueDays: number | null;
  questions: number;
  minutes: number;
  /** The chat request for this task: My Learning fills it in, the student sends it. */
  prompt: string;
  answeredToday: number;
  done: boolean;
};
export type PracticePlan = {
  date: string;
  timezone: string;
  budgetMinutes: number;
  budgetSource: "goal" | "default";
  insufficientHistory: boolean;
  /** The plan needs the student's class, 6 to 12 (Academic Profile), or one of the bank's subjects among theirs (Subjects & Study). */
  needsProfile: boolean;
  examDate: string | null;
  daysToExam: number | null;
  answeredToday: number;
  /** Practice answers that make a day a learning day (the streak). */
  answersForLearningDay: number;
  summary: {
    answered: number;
    practisedConcepts: number;
    masteredConcepts: number;
    weakConcepts: number;
    dueRevisions: number;
    overdueRevisions: number;
    recurringMistakes: number;
  };
  /** At most six, the same all day. */
  tasks: PlanTask[];
};

export type MasteryConcept = {
  conceptTag: string;
  objective: string;
  estimate: number;
  state: MasteryState;
  answered: number;
  correct: number;
  distinctQuestions: number;
  lastAnsweredAt: Timestamp;
};
export type MasteryTopic = {
  topicId: string;
  number: number;
  title: string;
  estimate: number | null;
  state: MasteryState;
  coverage: number;
  conceptCount: number;
  concepts: MasteryConcept[];
};
export type MasteryChapter = {
  chapterId: string;
  number: number;
  title: string;
  bookTitle: string;
  estimate: number | null;
  coverage: number;
  topicCount: number;
  topics: MasteryTopic[];
};
export type MasterySubject = {
  subjectCode: string;
  classLevel: number;
  language: PracticeLanguage;
  estimate: number | null;
  coverage: number;
  chapters: MasteryChapter[];
};
/** Practised items only: empty lists until there is evidence. */
export type Mastery = {
  model: {
    method: "bkt";
    prior: number;
    learn: number;
    guess: number;
    slip: number;
    masteredAt: number;
    minAnswers: number;
    minQuestions: number;
  };
  answered: number;
  revisedAnswers: number;
  subjects: MasterySubject[];
};

export type RevisionItem = {
  topicId: string;
  topicTitle: string;
  topicNumber: number;
  chapterId: string;
  chapterTitle: string;
  chapterNumber: number;
  bookTitle: string;
  subjectCode: string;
  classLevel: number;
  state: "overdue" | "due" | "done" | "upcoming";
  dueDate: string;
  overdueDays: number;
  intervalDays: number;
  recall: number;
  lastReviewed: string;
  lastAccuracy: number;
  reviews: number;
  estimate: number | null;
  prompt: string;
};
/** Overdue, then due (by forgetting risk), done, then upcoming (by due date). */
export type Revisions = { date: string; ladderDays: number[]; items: RevisionItem[] };

export type MistakeItem = {
  questionId: string;
  answeredAt: Timestamp;
  stem: string;
  options: string[];
  chosen: OptionLetter;
  correct: OptionLetter;
  explanation: string;
  /** Null once that chat was deleted (the evidence is kept). */
  conversationId: Uuid | null;
};
export type MistakeConcept = {
  topicId: string;
  topicTitle: string;
  chapterId: string;
  chapterTitle: string;
  chapterNumber: number;
  bookTitle: string;
  subjectCode: string;
  classLevel: number;
  conceptTag: string;
  objective: string;
  wrong: number;
  wrong14d: number;
  recurring: boolean;
  state: MasteryState;
  prompt: string;
  items: MistakeItem[];
};
export type Mistakes = { recurringRule: { wrong: number; days: number }; concepts: MistakeConcept[] };

export type PracticeTest = {
  setId: string;
  messageId: Uuid | null;
  /** Null once that chat was deleted (the test still counts). */
  conversationId: Uuid | null;
  title: string;
  chapterIds: string[];
  startedAt: Timestamp;
  total: number;
  served: number;
  answered: number;
  correct: number;
  open: boolean;
};
export type PracticeTests = { items: PracticeTest[] };

export type PracticeTopic = { topicId: string; number: number; title: string; questions: number };
export type PracticeChapter = { chapterId: string; number: number; title: string; questions: number; topics: PracticeTopic[] };
export type PracticeBook = { bookId: string; title: string; language: PracticeLanguage; chapters: PracticeChapter[] };
/** The bank's chapters for the student's class, in their medium plus the language subjects. */
export type PracticeTopics = {
  available: boolean;
  reason: "no_class" | "no_questions" | null;
  classLevel: number | null;
  language: "english" | "hindi";
  subjects: { subjectCode: string; books: PracticeBook[] }[];
};

// --------------------------------------------------------------- study time

export type StudyActivity = (typeof CONTRACT.StudyStartIn.activity.enum)[number];
export const STUDY_ACTIVITIES = CONTRACT.StudyStartIn.activity.enum;
export type StudyStatus = (typeof CONTRACT.StudySessionOut.status.enum)[number];
export type StudyEndReason = (typeof CONTRACT.StudySessionOut.endReason.enum)[number];
export type StudyContext = { subject?: string | null; chapterId?: string | null; activity: StudyActivity };

export type StudySegment = {
  id: Uuid;
  kind: "study" | "paused";
  subject: string | null;
  chapterId: string | null;
  bookId: string | null;
  chapterTitle: string | null;
  activity: StudyActivity;
  startedAt: Timestamp;
};
/** Seconds are the server's: the client never counts study time itself. */
export type StudySession = {
  id: Uuid;
  status: StudyStatus;
  startedAt: Timestamp;
  pausedAt: Timestamp | null;
  endedAt: Timestamp | null;
  endReason: StudyEndReason | null;
  timezone: string;
  segment: StudySegment | null;
  activeSeconds: number;
  idleSeconds: number;
  pausedSeconds: number;
  durationSeconds: number;
};
export type StudyState = {
  session: StudySession | null;
  lastEnded: StudySession | null;
  idle: { readingSeconds: number; solvingSeconds: number };
  serverTime: Timestamp;
};
export type StudyBeat = {
  beatId: Uuid;
  clientId: Uuid;
  wasActive: boolean;
  nowActive: boolean;
  studyView: boolean;
  visible: boolean;
};
export type StudyDay = {
  date: string;
  activeSeconds: number;
  idleSeconds: number;
  pausedSeconds: number;
  appSeconds: number;
};
export type StudySummary = {
  timezone: string;
  from: string;
  to: string;
  /** Days before it have no data (not listed) rather than zero. */
  firstRecordedDate: string | null;
  totals: { activeSeconds: number; idleSeconds: number; pausedSeconds: number; appSeconds: number; sessions: number };
  days: StudyDay[];
  subjects: { subject: string | null; activeSeconds: number }[];
  chapters: { subject: string | null; chapterId: string; bookId: string; chapterTitle: string; activeSeconds: number }[];
  activities: { activity: StudyActivity; activeSeconds: number }[];
  sessions: {
    id: Uuid;
    status: StudyStatus;
    endReason: StudyEndReason | null;
    startedAt: Timestamp;
    endedAt: Timestamp | null;
    activeSeconds: number;
    idleSeconds: number;
    pausedSeconds: number;
    durationSeconds: number;
    subjects: (string | null)[];
    chapters: string[];
    activities: StudyActivity[];
  }[];
};
export type StudyChapters = {
  available: boolean;
  reason: "no_class" | "unavailable" | "not_configured" | null;
  chapters: { chapterId: string; bookId: string; number: number | null; label: string | null; title: string }[];
};

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

/** The password rule Better Auth enforces (lib/auth/config.ts, emailAndPassword). */
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
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

/**
 * What a reply's `[1]` (a knowledge source) or `[F1]` (a file the student attached) points at:
 * titles only. `fileId` for files, to preview their own copy.
 */
export type Citation = { ref: string; kind: "source" | "file"; title: string; fileId?: Uuid };

export type MessageMetadata = {
  model?: string;
  /** e.g. `llm_timeout`, or `interrupted` for a reply swept after a crash. */
  errorCode?: string;
  finishReason?: string;
  /** Only on replies whose prompt numbered sources or files; arrives with the finished reply. */
  citations?: Citation[];
  /** The reply's practice test as the server recorded it (at most one per reply). */
  assessments?: Assessment[];
  /** The reply wrote a test the server could not accept whole (no test was kept). */
  assessmentError?: { code: string };
  /** Client-side, voice turns only (the stream's `expression`): the tutor face's manner; never shown as text. */
  expression?: string;
  /** Client-side, voice turns only (the stream's `speech`): the reply's first words, spoken by the server. */
  speech?: StreamSpeech;
};

// --------------------------------------------------------- practice tests

/** One question's recorded response: final, graded by the server. */
export type AssessmentAnswer = {
  status: "answered" | "skipped";
  /** The chosen option (0-based) of a multiple-choice question, or the text typed into each blank; null when skipped. */
  value: number | string[] | null;
  earned: number;
  possible: number;
  at: string;
  /** Fill-in-the-blanks: whether each blank was right. */
  marks: boolean[] | null;
};

/**
 * One question. Multiple choice (`mcq`) has `text` and `options`; a fill-in-the-blanks exercise
 * (`fill_blank`) has `segments` (the text around the blanks) and `blanks`. The rest are null.
 */
export type AssessmentQuestion = {
  kind: "mcq" | "fill_blank";
  text: string | null;
  options: string[] | null;
  segments: string[] | null;
  blanks: number | null;
  response: AssessmentAnswer | null;
  /** The right option (multiple choice): only once this question has a response. */
  correct: number | null;
  /** The accepted answers of each blank (fill-in-the-blanks): only once answered or skipped. */
  answers: string[][] | null;
  explanation: string | null;
};

/**
 * A practice test or fill-in-the-blanks exercise in a reply (`POST /v1/messages/{id}/assessment-responses`).
 * The server owns it: questions come from the saved reply, answers are final, in order and graded
 * there. `locator` says which block of the reply it is (sha256 of the block's source, trimmed).
 */
export type Assessment = {
  id: string;
  position: number;
  schemaVersion: number;
  kind: "test" | "exercise";
  title: string | null;
  hash: string;
  locator: string;
  state: "not_started" | "active" | "completed";
  answerable: boolean;
  total: number;
  answered: number;
  /** The waiting question; null once completed. */
  current: number | null;
  earned: number;
  possible: number;
  questions: AssessmentQuestion[];
};

/**
 * What an answer returns: the test as recorded, and `learning` only when this answer made its day a
 * learning day (question-bank answers count in fives; the server reports the day once, like `done`).
 */
export type AssessmentResponse = Assessment & { learning?: StreamLearning | null };

export type AssessmentResponseRequest = {
  position: number;
  hash: string;
  question: number;
  action: "answer" | "skip";
  /** Answers only: an option's index, or one text per blank. */
  value?: number | string[];
};

/** A file attached to a user message. `fileId` is null once the file was deleted (the name stays). */
export type MessageAttachment = { fileId: Uuid | null; filename: string };

export type Message = {
  id: Uuid;
  conversationId: Uuid;
  role: MessageRole;
  /** Raw Markdown exactly as the model produced it. */
  content: string;
  status: MessageStatus;
  createdAt: Timestamp;
  metadata?: MessageMetadata;
  /** User messages only; absent or empty when nothing was attached. */
  attachments?: MessageAttachment[];
};

export type MessagePage = { items: Message[]; nextCursor: string | null };

// -------------------------------------------------------------------- chat

export type ChatRequest = {
  conversationId?: Uuid | null;
  message: string;
  attachmentIds?: Uuid[];
  /** "voice": spoken in voice mode, the reply will be read aloud (a typed message for anyone it is not for). */
  mode?: "text" | "voice";
  /** Voice turns: the audio this browser decodes, for the first words the server speaks (`serverSpeech`). */
  speechFormat?: SpeechFormat;
};
/** The API rejects longer messages (the contract's ChatRequest.message). */
export const MESSAGE_MAX = CONTRACT.ChatRequest.message.maxLength;
/** Files one message may attach (the contract's ChatRequest.attachmentIds). */
export const ATTACHMENTS_MAX = CONTRACT.ChatRequest.attachmentIds.maxItems;

// -------------------------------------------------------------------- voice
/**
 * GET /v1/voice: whether voice mode is offered to this student (every voice route checks it too), whether a
 * short pre-recorded word is said when they stop speaking (`ack`), and whether the server speaks a reply's first
 * words itself (`serverSpeech`: the stream's `speech` events).
 */
export type VoiceAvailability = { enabled: boolean; ack?: boolean; serverSpeech?: boolean };
/** POST /v1/voice/transcriptions: what was said; "" when nothing was heard. */
export type VoiceTranscript = { text: string; seconds: number | null };
/** The audio a browser decodes, smallest first: Ogg Opus, ADTS AAC, MP3. */
export type SpeechFormat = "opus" | "aac" | "mp3";
/** POST /v1/voice/speech: one sentence of the student's own reply. */
export type SpeechRequest = { messageId: Uuid; text: string; format?: SpeechFormat };

// -------------------------------------------------------------------- files

export type FileKind = (typeof CONTRACT.FileOut.kind.enum)[number];
/** processing: being read; ready: the tutor can use it; failed: see errorCode; stored: kept, not readable now. */
export type FileStatus = (typeof CONTRACT.FileOut.status.enum)[number];
export type LibraryFile = {
  id: Uuid;
  filename: string;
  kind: FileKind;
  sizeBytes: number;
  status: FileStatus;
  errorCode: string | null;
  retryable: boolean;
  createdAt: Timestamp;
  updatedAt: Timestamp;
};
export type FileUsage = { usedBytes: number; quotaBytes: number; remainingBytes: number };
export type FileList = { items: LibraryFile[]; usage: FileUsage };

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

/** What the reply's [1] / [F1] markers point at; sent before the first token when there are any. */
export type StreamCitations = { messageId: Uuid; citations: Citation[] };

/** Voice turns only, before the first token: the tutor face's manner for this reply (never shown as text). */
export type StreamExpression = { messageId: Uuid; expression: string };

/**
 * Voice turns only (`serverSpeech`): the reply's first words, spoken by the server. `planned`: its first `chars`
 * characters are `text`, being spoken; then `ready` (the audio, base64, of `type`) or `failed` (the client
 * speaks them itself). `skipped`: the server speaks none of it.
 */
export type StreamSpeech = {
  messageId: Uuid;
  state: "planned" | "ready" | "failed" | "skipped";
  chars?: number;
  text?: string;
  type?: string;
  audio?: string;
};

/** Authoritative final state. `message.status` may be `cancelled`. */
/** What the answer did to the learning streak: only on the answer that made its day a learning day. */
export type StreamLearning = { event: "started" | "extended" | "milestone"; streak: number };
export type StreamDone = { message: Message; conversation: Conversation; learning?: StreamLearning };

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
