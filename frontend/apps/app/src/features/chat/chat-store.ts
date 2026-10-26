/**
 * Client-side state for every open conversation — and nothing the server owns.
 *
 * The server is the source of truth for conversations and messages. This store
 * holds what the browser genuinely owns: the transcript it has loaded, the reply
 * being streamed right now, the text being typed, and transient errors.
 *
 * WHY A STORE, AND WHY THIS SHAPE
 *
 *   - ONE ENTRY PER CONVERSATION. The old page had a single `busy` flag, so a reply
 *     streaming in chat A disabled chat B. Here each entry has its own stream.
 *   - STREAMS OUTLIVE THE PAGE. Streams belong to the store (created once by the
 *     app shell), not to a component, so switching chats or opening Settings never
 *     stops a reply, and coming back shows it still arriving.
 *   - PER-KEY SUBSCRIPTIONS. The list subscribes to its `order`; each message
 *     subscribes to itself. A streamed token changes one message object and
 *     notifies only that message's subscribers — the transcript does not
 *     re-render per token (the old page rebuilt the whole array every token).
 *     Tokens are also batched (default ~50 ms) before they touch React at all.
 *   - DRAFT KEYS. A new chat has no id until the server sends `meta` (the contract
 *     says not to create one up front). It lives under `draft:n`; on `meta` the
 *     draft key becomes an alias of the real id, so whatever was watching the draft
 *     keeps receiving updates.
 *   - NOTHING IS WRITTEN FROM HERE. The API persists both sides of every turn. The
 *     old page wrote messages itself (fire-and-forget), which is how a deleted chat
 *     could be resurrected by a late reply.
 */

import { LETTERS, type TestCommand, parseTestCommand } from "@/features/markdown/assessment";
import type { TestNotice } from "@/features/markdown/context";
import type { StreamHandlers, StreamOutcome } from "@/lib/api/chat";
import { ApiError, type ErrorCode, describeError, isAbortError } from "@/lib/api/errors";
import type {
  Assessment,
  AssessmentResponse,
  AssessmentResponseRequest,
  ChatRequest,
  Conversation,
  FeedbackRating,
  Message,
  MessageAttachment,
  MessagePage,
  SpeechFormat,
  StreamDone,
  StreamFailure,
  StreamLearning,
  StreamMeta,
} from "@/lib/api/types";
import { MESSAGE_MAX } from "@/lib/api/types";

export type ChatApi = {
  streamChat: (request: ChatRequest, handlers: StreamHandlers, options: { signal?: AbortSignal }) => Promise<StreamOutcome>;
  streamRegenerate: (
    conversationId: string,
    handlers: StreamHandlers,
    options: { signal?: AbortSignal },
  ) => Promise<StreamOutcome>;
  cancelMessage: (messageId: string) => Promise<unknown>;
  listMessages: (
    conversationId: string,
    options: { limit?: number; before?: string | null },
  ) => Promise<MessagePage>;
  setFeedback: (messageId: string, rating: FeedbackRating) => Promise<unknown>;
  clearFeedback: (messageId: string) => Promise<unknown>;
  deleteConversation: (conversationId: string) => Promise<void>;
  respondToAssessment: (messageId: string, request: AssessmentResponseRequest) => Promise<AssessmentResponse>;
};

export type MessageError = { code: ErrorCode; retryable: boolean; requestId?: string };

/** A message as the UI sees it: the server's message plus local, transient state. */
export type ChatMessage = Message & {
  /** Why this reply failed (stream `error`, or the connection dropped). */
  failure?: MessageError;
  /** The user's 👍/👎 chosen in this session (the API does not return it — contract gap). */
  feedback?: FeedbackRating | null;
  /** Shown optimistically; not yet confirmed by the server. */
  pending?: boolean;
  /** The last typed command that reached this reply's practice test (its card shows it). */
  testNotice?: TestNotice;
};

export type EntryStatus = "idle" | "loading" | "ready" | "not_found" | "error";
export type StreamPhase = "starting" | "streaming" | "stopping";

export type ChatEntry = Readonly<{
  key: string;
  conversationId: string | null;
  status: EntryStatus;
  loadError: MessageError | null;
  order: readonly string[];
  nextCursor: string | null;
  loadingOlder: boolean;
  stream: Readonly<{ phase: StreamPhase; assistantId: string | null }> | null;
  /**
   * A send that never reached a reply (409, 429, 413, offline …). When set, the
   * unsent text has been put back in the draft (`getDraft`).
   */
  composerError: MessageError | null;
}>;

type Runtime = {
  controller: AbortController | null;
  buffer: string;
  flushCancel: (() => void) | null;
  flushPending: boolean;
  stopTimer: ReturnType<typeof setTimeout> | null;
  /** Why the current stream is being torn down: a user stop, or the chat going away. */
  teardown: "stop" | "discard" | null;
};

type Listener = () => void;
export type Scheduler = (run: () => void) => () => void;

export type ChatStoreOptions = {
  api: ChatApi;
  /** How token flushes are scheduled. Default: ~50 ms timer. */
  schedule?: Scheduler;
  /** How long Stop waits for the server's final `done` before cutting the connection. */
  stopGraceMs?: number;
  now?: () => Date;
  onConversationCreated?: (conversation: Conversation, draftKey: string) => void;
  onConversationUpdated?: (conversation: Conversation) => void;
};

const defaultSchedule: Scheduler = (run) => {
  const timer = setTimeout(run, 50);
  return () => clearTimeout(timer);
};

function emptyEntry(key: string, conversationId: string | null, status: EntryStatus): ChatEntry {
  return {
    key,
    conversationId,
    status,
    loadError: null,
    order: [],
    nextCursor: null,
    loadingOlder: false,
    stream: null,
    composerError: null,
  };
}

function failureFrom(error: unknown): MessageError {
  const description = describeError(error);
  return {
    code: description.code,
    retryable: description.action === "retry",
    requestId: description.requestId,
  };
}

export class ChatStore {
  private readonly api: ChatApi;
  private readonly schedule: Scheduler;
  private readonly stopGraceMs: number;
  private readonly now: () => Date;

  /** Canonical key → entry. A conversation's canonical key is its id. */
  private readonly entries = new Map<string, ChatEntry>();
  private readonly messages = new Map<string, Map<string, ChatMessage>>();
  private readonly runtimes = new Map<string, Runtime>();
  /** draft key → conversation id, once the server has created the conversation. */
  private readonly aliases = new Map<string, string>();
  private readonly drafts = new Map<string, string>();

  private readonly entryListeners = new Map<string, Set<Listener>>();
  private readonly messageListeners = new Map<string, Set<Listener>>();

  private draftCounter = 0;
  private localCounter = 0;
  private noticeCounter = 0;
  /** The conversation (or draft) currently on screen. */
  activeKey: string | null = null;

  onConversationCreated?: (conversation: Conversation, draftKey: string) => void;
  onConversationUpdated?: (conversation: Conversation) => void;
  /** A reply finished (the streak may have changed: the header and the bell refresh). */
  onReplyFinished?: (done: StreamDone) => void;
  /**
   * A practice question was answered (the streak may have changed: the header and the bell
   * refresh, after a retried answer too, whose response never has `learning`). `learning` when
   * this answer made its day a learning day (the server says so once): `answered` keys it.
   */
  onPracticeAnswered?: (learning: StreamLearning | null, messageId: string, answered: number) => void;

  constructor(options: ChatStoreOptions) {
    this.api = options.api;
    this.schedule = options.schedule ?? defaultSchedule;
    this.stopGraceMs = options.stopGraceMs ?? 3000;
    this.now = options.now ?? (() => new Date());
    this.onConversationCreated = options.onConversationCreated;
    this.onConversationUpdated = options.onConversationUpdated;
  }

  // ------------------------------------------------------------- reading

  resolve(key: string): string {
    return this.aliases.get(key) ?? key;
  }

  getEntry(key: string): ChatEntry | undefined {
    return this.entries.get(this.resolve(key));
  }

  getMessage(key: string, messageId: string): ChatMessage | undefined {
    return this.messages.get(this.resolve(key))?.get(messageId);
  }

  isStreaming(key: string): boolean {
    return Boolean(this.getEntry(key)?.stream);
  }

  /** Whether a reply is streaming in any conversation (the activity heartbeat counts that). */
  anyStreaming(): boolean {
    for (const entry of this.entries.values()) if (entry.stream) return true;
    return false;
  }

  subscribe(key: string, listener: Listener): () => void {
    return this.addListener(this.entryListeners, this.resolve(key), listener);
  }

  subscribeMessage(key: string, messageId: string, listener: Listener): () => void {
    return this.addListener(this.messageListeners, `${this.resolve(key)}\u0000${messageId}`, listener);
  }

  /** Number of registered listeners (tests assert per-token fan-out with this). */
  listenerCount(kind: "entry" | "message", id: string): number {
    const map = kind === "entry" ? this.entryListeners : this.messageListeners;
    return map.get(id)?.size ?? 0;
  }

  // --------------------------------------------------------------- drafts

  /**
   * A key for a new, empty chat. Reuses the last draft while it is still unused,
   * so revisiting "New chat" does not pile up entries; a draft that has sent a
   * message (or is sending one) is never reused — that is how two new chats
   * started back to back stay separate.
   */
  freshDraftKey(): string {
    if (this.draftCounter > 0) {
      const last = `draft:${this.draftCounter}`;
      const entry = this.entries.get(last);
      if (!this.aliases.has(last) && entry && entry.order.length === 0 && !entry.stream) return last;
    }
    this.draftCounter += 1;
    const key = `draft:${this.draftCounter}`;
    this.entries.set(key, emptyEntry(key, null, "ready"));
    return key;
  }

  /**
   * Unsent text, per conversation, in memory only (never storage). Deliberately
   * silent: typing must not notify the message list on every keystroke.
   */
  setDraft(key: string, text: string): void {
    this.drafts.set(this.resolve(key), text);
  }

  getDraft(key: string): string {
    return this.drafts.get(this.resolve(key)) ?? "";
  }

  clearComposerError(key: string): void {
    if (this.getEntry(key)?.composerError) this.update(key, { composerError: null });
  }

  // -------------------------------------------------------------- loading

  /** Load a conversation's latest messages once. */
  async ensureLoaded(conversationId: string): Promise<void> {
    const existing = this.getEntry(conversationId);
    if (existing && existing.status !== "idle" && existing.status !== "error") return;
    await this.reload(conversationId);
  }

  /** (Re)read the latest page from the server — a read, never a generation. */
  async reload(conversationId: string): Promise<void> {
    const key = this.resolve(conversationId);
    const current = this.entries.get(key);
    if (current?.stream) return; // the live stream is more current than the server
    if (!current) this.entries.set(key, emptyEntry(key, conversationId, "loading"));
    else this.update(key, { status: "loading", loadError: null });
    this.notifyEntry(key);
    try {
      const page = await this.api.listMessages(conversationId, { limit: 50 });
      if (this.entries.get(key)?.stream) return;
      const previous = this.messages.get(key);
      const map = new Map<string, ChatMessage>();
      for (const message of page.items) {
        const kept = previous?.get(message.id);
        map.set(message.id, kept?.feedback ? { ...message, feedback: kept.feedback } : message);
      }
      this.messages.set(key, map);
      this.update(key, {
        status: "ready",
        order: page.items.map((message) => message.id),
        nextCursor: page.nextCursor,
        loadError: null,
      });
      for (const id of map.keys()) this.notifyMessage(key, id);
    } catch (error) {
      if (error instanceof ApiError && error.code === "not_found") {
        this.update(key, { status: "not_found" });
      } else {
        this.update(key, { status: "error", loadError: failureFrom(error) });
      }
    }
  }

  /** Load the page before the oldest message on screen. */
  async loadOlder(conversationId: string): Promise<void> {
    const key = this.resolve(conversationId);
    const entry = this.entries.get(key);
    if (!entry?.nextCursor || entry.loadingOlder) return;
    this.update(key, { loadingOlder: true });
    try {
      const page = await this.api.listMessages(conversationId, { limit: 50, before: entry.nextCursor });
      const map = this.messageMap(key);
      const known = new Set(this.entries.get(key)?.order);
      const older = page.items.filter((message) => !known.has(message.id));
      for (const message of older) map.set(message.id, message);
      this.update(key, {
        order: [...older.map((message) => message.id), ...(this.entries.get(key)?.order ?? [])],
        nextCursor: page.nextCursor,
        loadingOlder: false,
      });
    } catch (error) {
      this.update(key, { loadingOlder: false, loadError: failureFrom(error) });
    }
  }

  // -------------------------------------------------------------- sending

  /**
   * A send refused before the turn existed gave its text back to the draft; these are the files
   * it attached (ChatProvider gives them back to the composer too).
   */
  onSendRefused?: (key: string, attachments: MessageAttachment[]) => void;

  /** Send a message in a conversation (or a draft, which the server then creates), with ready files. */
  async send(
    key: string,
    rawText: string,
    attachments: MessageAttachment[] = [],
    options: { mode?: "voice"; speechFormat?: SpeechFormat } = {},
  ): Promise<void> {
    const text = rawText.trim();
    const entry = this.ensureEntry(key);
    if (!text || entry.stream) return;
    const canonical = this.resolve(key);
    if (text.length > MESSAGE_MAX) {
      this.update(canonical, { composerError: { code: "payload_too_large", retryable: false } });
      return;
    }
    // A letter, "skip" or "next" goes to the chat's latest unfinished practice test, not the tutor.
    const command = attachments.length ? null : parseTestCommand(text);
    const target = command ? this.testTarget(canonical) : null;
    if (command && target) return this.typedTestCommand(canonical, command, target);

    const optimisticId = `local:${++this.localCounter}`;
    const optimistic: ChatMessage = {
      id: optimisticId,
      conversationId: entry.conversationId ?? "",
      role: "user",
      content: text,
      status: "complete",
      createdAt: this.now().toISOString(),
      pending: true,
      ...(attachments.length ? { attachments } : {}),
    };
    this.messageMap(canonical).set(optimisticId, optimistic);
    this.drafts.set(canonical, "");
    this.update(canonical, {
      order: [...entry.order, optimisticId],
      composerError: null,
    });

    const request: ChatRequest = { conversationId: entry.conversationId, message: text };
    if (attachments.length) request.attachmentIds = attachments.flatMap((a) => (a.fileId ? [a.fileId] : []));
    if (options.mode === "voice") request.mode = "voice"; // spoken in voice mode (features/voice)
    if (options.mode === "voice" && options.speechFormat) request.speechFormat = options.speechFormat;
    await this.runStream(key, optimisticId, text, (handlers, signal) =>
      this.api.streamChat(request, handlers, { signal }),
    );
  }

  /** Replace the last reply with a new one (also the "Retry" of a failed reply). */
  async regenerate(conversationId: string): Promise<void> {
    const entry = this.getEntry(conversationId);
    if (!entry?.conversationId || entry.stream) return;
    await this.runStream(conversationId, null, null, (handlers, signal) =>
      this.api.streamRegenerate(conversationId, handlers, { signal }),
    );
  }

  /** The reply that "Regenerate" would replace: the last assistant message, if last. */
  lastAssistantId(key: string): string | null {
    const entry = this.getEntry(key);
    const lastId = entry?.order.at(-1);
    if (!lastId) return null;
    const last = this.getMessage(key, lastId);
    return last?.role === "assistant" ? last.id : null;
  }

  private async runStream(
    key: string,
    optimisticId: string | null,
    sentText: string | null,
    open: (handlers: StreamHandlers, signal: AbortSignal) => Promise<StreamOutcome>,
  ): Promise<void> {
    const controller = new AbortController();
    const draftKey = key;
    let canonical = this.resolve(key);
    this.runtimes.set(canonical, {
      controller,
      buffer: "",
      flushCancel: null,
      flushPending: false,
      stopTimer: null,
      teardown: null,
    });
    this.update(canonical, { stream: { phase: "starting", assistantId: null } });

    let assistantId: string | null = null;

    const handlers: StreamHandlers = {
      onMeta: (meta: StreamMeta) => {
        assistantId = meta.assistantMessageId;
        const before = canonical;
        canonical = this.adopt(before, meta.conversationId);
        const map = this.messageMap(canonical);
        let order = [...(this.entries.get(canonical)?.order ?? [])];

        if (optimisticId && meta.userMessage) {
          map.delete(optimisticId);
          map.set(meta.userMessage.id, meta.userMessage);
          order = order.map((id) => (id === optimisticId ? (meta.userMessage?.id ?? id) : id));
        }
        if (meta.replacesMessageId) {
          map.delete(meta.replacesMessageId);
          order = order.filter((id) => id !== meta.replacesMessageId);
        }
        map.set(meta.assistantMessageId, {
          id: meta.assistantMessageId,
          conversationId: meta.conversationId,
          role: "assistant",
          content: "",
          status: "streaming",
          createdAt: this.now().toISOString(),
        });
        order.push(meta.assistantMessageId);
        this.update(canonical, { order, stream: { phase: "streaming", assistantId } });

        if (before !== canonical) this.onConversationCreated?.(meta.conversation, draftKey);
        else this.onConversationUpdated?.(meta.conversation);
      },
      onToken: ({ text }) => {
        const runtime = this.runtimes.get(canonical);
        if (!runtime || !assistantId) return;
        runtime.buffer += text;
        if (!runtime.flushPending) {
          const id = assistantId;
          runtime.flushPending = true;
          runtime.flushCancel = this.schedule(() => {
            runtime.flushPending = false;
            runtime.flushCancel = null;
            this.flush(canonical, id);
          });
        }
      },
      onCitations: ({ messageId, citations }) => {
        // The reply's [1] / [F1] become chips while it is still being written.
        const current = this.getMessage(canonical, messageId);
        if (current) this.putMessage(canonical, { ...current, metadata: { ...current.metadata, citations } });
      },
      onExpression: ({ messageId, expression }) => {
        // Voice mode: the face's manner for this reply, before its first words.
        const current = this.getMessage(canonical, messageId);
        if (current) this.putMessage(canonical, { ...current, metadata: { ...current.metadata, expression } });
      },
      onSpeech: (speech) => {
        // Voice mode: the reply's first words, spoken by the server (read by features/voice, never shown).
        const current = this.getMessage(canonical, speech.messageId);
        if (current) this.putMessage(canonical, { ...current, metadata: { ...current.metadata, speech } });
      },
      onDone: (done: StreamDone) => {
        this.flush(canonical, done.message.id);
        this.putMessage(canonical, { ...done.message, feedback: this.getMessage(canonical, done.message.id)?.feedback });
        this.onConversationUpdated?.(done.conversation);
        this.onReplyFinished?.(done);
      },
      onError: (failure: StreamFailure) => {
        const id = failure.messageId ?? assistantId;
        if (!id) return;
        this.flush(canonical, id);
        const current = this.getMessage(canonical, id);
        if (current) {
          this.putMessage(canonical, {
            ...current,
            status: "error",
            failure: {
              code: describeError(new ApiError(0, failure.code)).code,
              retryable: failure.retryable,
              requestId: failure.requestId,
            },
          });
        }
      },
    };

    let outcome: StreamOutcome | "failed" = "failed";
    let failure: MessageError | null = null;
    try {
      outcome = await open(handlers, controller.signal);
    } catch (error) {
      failure = isAbortError(error) ? null : failureFrom(error);
      outcome = isAbortError(error) ? "aborted" : "failed";
    }

    const runtime = this.runtimes.get(canonical);
    if (runtime?.flushCancel) runtime.flushCancel();
    if (runtime?.stopTimer) clearTimeout(runtime.stopTimer);
    const teardown = runtime?.teardown ?? null;
    this.runtimes.delete(canonical);

    if (teardown === "discard") return; // the conversation is being deleted / signed out

    if (assistantId) this.flush(canonical, assistantId, runtime?.buffer ?? "");

    if (outcome === "failed" && !assistantId) {
      // Refused before the turn existed (409 / 429 / 413 / 422 / offline): nothing was
      // saved. Take the optimistic message back and give the text back to the composer.
      const map = this.messageMap(canonical);
      const entry = this.entries.get(canonical);
      const refused = optimisticId ? map.get(optimisticId)?.attachments : undefined;
      if (optimisticId) map.delete(optimisticId);
      if (refused?.length) this.onSendRefused?.(canonical, refused);
      if (refused?.length && failure?.code === "validation_error") {
        failure = { ...failure, code: "attachment_unavailable" };
      }
      this.drafts.set(canonical, this.drafts.get(canonical) || sentText || "");
      this.update(canonical, {
        stream: null,
        order: (entry?.order ?? []).filter((id) => id !== optimisticId),
        composerError: failure,
      });
      return;
    }

    if (assistantId && (outcome === "interrupted" || outcome === "failed" || outcome === "aborted")) {
      const current = this.getMessage(canonical, assistantId);
      if (current && current.status === "streaming") {
        this.putMessage(canonical, {
          ...current,
          status: teardown === "stop" ? "cancelled" : "error",
          failure:
            teardown === "stop"
              ? undefined
              : { code: outcome === "failed" && failure ? failure.code : "stream_interrupted", retryable: true },
        });
      }
    }

    this.update(canonical, { stream: null });

    // The connection dropped without a final event: show what the server actually
    // kept. This re-reads the conversation; it never asks for another reply.
    if (outcome === "interrupted" && teardown !== "stop") {
      const conversationId = this.entries.get(canonical)?.conversationId;
      if (conversationId) void this.reload(conversationId);
    }
  }

  /** Stop the reply streaming in `key`. */
  async stop(key: string): Promise<void> {
    const canonical = this.resolve(key);
    const entry = this.entries.get(canonical);
    const runtime = this.runtimes.get(canonical);
    if (!entry?.stream || !runtime) return;
    runtime.teardown = "stop";
    const assistantId = entry.stream.assistantId;
    if (!assistantId) {
      // Before `meta` there is no id to cancel; closing the connection is the stop
      // (the API treats a disconnect as cancel).
      runtime.controller?.abort();
      return;
    }
    this.update(canonical, { stream: { phase: "stopping", assistantId } });
    // The API marks the reply cancelled and the open stream then ends with `done`
    // carrying the persisted partial text. Wait briefly for it, then cut the cord.
    runtime.stopTimer = setTimeout(() => runtime.controller?.abort(), this.stopGraceMs);
    try {
      await this.api.cancelMessage(assistantId);
    } catch {
      runtime.controller?.abort();
    }
  }

  // ------------------------------------------------------------- feedback

  async setFeedback(key: string, messageId: string, rating: FeedbackRating | null): Promise<void> {
    const current = this.getMessage(key, messageId);
    if (!current || current.role !== "assistant") return;
    const previous = current.feedback ?? null;
    this.putMessage(this.resolve(key), { ...current, feedback: rating });
    try {
      if (rating) await this.api.setFeedback(messageId, rating);
      else await this.api.clearFeedback(messageId);
    } catch (error) {
      const latest = this.getMessage(key, messageId);
      if (latest) this.putMessage(this.resolve(key), { ...latest, feedback: previous });
      throw error;
    }
  }

  // -------------------------------------------------------- practice tests

  /**
   * Answer or skip the waiting question of a reply's practice test. The server grades and records
   * it, and the reply's test becomes what it returns; an answer goes on to `onPracticeAnswered`,
   * with its `learning` when it made its day a learning day, like a reply's `done`. A 409 means
   * the test moved on elsewhere (another tab) or was replaced: the conversation is read again.
   * Errors are rethrown for the card.
   */
  async respondToTest(
    key: string,
    messageId: string,
    position: number,
    request: Omit<AssessmentResponseRequest, "position">,
  ): Promise<void> {
    const canonical = this.resolve(key);
    try {
      const { learning, ...test } = await this.api.respondToAssessment(messageId, { position, ...request });
      if (request.action === "answer") this.onPracticeAnswered?.(learning ?? null, messageId, test.answered);
      const current = this.getMessage(canonical, messageId);
      const tests = current?.metadata?.assessments;
      const index = tests?.findIndex((item) => item.position === position) ?? -1;
      // Responses only ever grow: a late reply never puts an older state back.
      if (!current || !tests || index < 0 || (tests[index]?.answered ?? 0) > test.answered) return;
      const next = tests.map((item, at) => (at === index ? test : item));
      this.putMessage(canonical, { ...current, metadata: { ...current.metadata, assessments: next } });
    } catch (error) {
      const conversationId = this.entries.get(canonical)?.conversationId;
      if (error instanceof ApiError && error.status === 409 && conversationId) void this.reload(conversationId);
      throw error;
    }
  }

  /**
   * The test typed commands reach: the chat's latest practice block, only when it is a test that
   * waits for an answer. An older unfinished test is answered through its own card; a finished
   * test, or an exercise, takes none.
   */
  testTarget(key: string): { messageId: string; test: Assessment } | null {
    const canonical = this.resolve(key);
    const order = this.entries.get(canonical)?.order ?? [];
    for (let index = order.length - 1; index >= 0; index -= 1) {
      const message = this.getMessage(canonical, order[index] ?? "");
      if (message?.role !== "assistant" || message.status !== "complete") continue;
      const test = message.metadata?.assessments?.at(-1);
      if (!test) continue;
      // A typed letter, skip or next is for a multiple-choice test; never for an exercise.
      return test.kind === "test" && test.answerable && test.current !== null ? { messageId: message.id, test } : null;
    }
    return null;
  }

  /** A typed letter / skip / next, applied to the latest unfinished test (never sent to the tutor). */
  private async typedTestCommand(
    canonical: string,
    command: TestCommand,
    { messageId, test }: { messageId: string; test: Assessment },
  ): Promise<void> {
    const question = test.current ?? 0;
    const options = test.questions[question]?.options?.length ?? 0;
    const say = (notice: string) => this.noticeTest(canonical, messageId, test.position, notice);
    if (command.kind === "show") {
      say(`Question ${question + 1} of ${test.total} is waiting: pick an option, or type skip.`);
      return;
    }
    if (command.kind === "answer" && command.value >= options) {
      say(`Question ${question + 1} has options A to ${LETTERS[options - 1]}.`);
      return;
    }
    try {
      await this.respondToTest(canonical, messageId, test.position, {
        hash: test.hash,
        question,
        ...(command.kind === "answer" ? { action: "answer", value: command.value } : { action: "skip" }),
      });
      say(
        command.kind === "answer"
          ? `You answered ${LETTERS[command.value]} to question ${question + 1}.`
          : `You skipped question ${question + 1}.`,
      );
    } catch (error) {
      say(
        error instanceof ApiError && error.status === 409
          ? "This test moved on elsewhere (another tab?). It now shows where it is."
          : "Your answer wasn't saved. Check your connection and try again.",
      );
    }
  }

  private noticeTest(canonical: string, messageId: string, position: number, text: string): void {
    const current = this.getMessage(canonical, messageId);
    if (current) this.putMessage(canonical, { ...current, testNotice: { position, text, seq: ++this.noticeCounter } });
  }

  // ------------------------------------------------------------- deleting

  /**
   * Delete a conversation. A reply still streaming is stopped first, so nothing
   * is left generating into a conversation that no longer exists. Throws if the
   * API refuses; the chat stays intact in that case.
   */
  async deleteConversation(conversationId: string): Promise<void> {
    const canonical = this.resolve(conversationId);
    const entry = this.entries.get(canonical);
    const runtime = this.runtimes.get(canonical);
    if (entry?.stream && runtime) {
      runtime.teardown = "discard";
      if (entry.stream.assistantId) await this.api.cancelMessage(entry.stream.assistantId).catch(() => undefined);
      runtime.controller?.abort();
    }
    await this.api.deleteConversation(conversationId);
    this.forget(canonical);
  }

  /** Drop everything for a conversation from memory (after delete). */
  forget(conversationId: string): void {
    const canonical = this.resolve(conversationId);
    this.runtimes.get(canonical)?.controller?.abort();
    this.runtimes.delete(canonical);
    this.messages.delete(canonical);
    this.drafts.delete(canonical);
    if (this.entries.has(canonical)) {
      this.entries.set(canonical, emptyEntry(canonical, conversationId, "not_found"));
      this.notifyEntry(canonical);
    }
  }

  /** Sign-out: abort every stream and forget everything. */
  reset(): void {
    for (const runtime of this.runtimes.values()) {
      runtime.teardown = "discard";
      runtime.controller?.abort();
      runtime.flushCancel?.();
      if (runtime.stopTimer) clearTimeout(runtime.stopTimer);
    }
    this.runtimes.clear();
    this.entries.clear();
    this.messages.clear();
    this.aliases.clear();
    this.drafts.clear();
    this.activeKey = null;
  }

  // ------------------------------------------------------------- internals

  private ensureEntry(key: string): ChatEntry {
    const canonical = this.resolve(key);
    let entry = this.entries.get(canonical);
    if (!entry) {
      const isDraft = canonical.startsWith("draft:");
      entry = emptyEntry(canonical, isDraft ? null : canonical, isDraft ? "ready" : "idle");
      this.entries.set(canonical, entry);
    }
    return entry;
  }

  private messageMap(canonical: string): Map<string, ChatMessage> {
    let map = this.messages.get(canonical);
    if (!map) {
      map = new Map();
      this.messages.set(canonical, map);
    }
    return map;
  }

  /** On `meta`: a draft becomes the real conversation, and the draft key an alias. */
  private adopt(canonical: string, conversationId: string): string {
    if (canonical === conversationId) return canonical;
    const entry = this.entries.get(canonical);
    if (!entry) return conversationId;
    this.entries.set(conversationId, { ...entry, key: conversationId, conversationId, status: "ready" });
    this.entries.delete(canonical);
    const map = this.messages.get(canonical);
    if (map) {
      for (const message of map.values()) message.conversationId ||= conversationId;
      this.messages.set(conversationId, map);
      this.messages.delete(canonical);
    }
    const runtime = this.runtimes.get(canonical);
    if (runtime) {
      this.runtimes.set(conversationId, runtime);
      this.runtimes.delete(canonical);
    }
    const draftText = this.drafts.get(canonical);
    if (draftText !== undefined) {
      this.drafts.set(conversationId, draftText);
      this.drafts.delete(canonical);
    }
    this.aliases.set(canonical, conversationId);
    if (this.activeKey === canonical) this.activeKey = conversationId;
    this.moveListeners(this.entryListeners, canonical, conversationId);
    for (const [id, set] of [...this.messageListeners]) {
      if (id.startsWith(`${canonical}\u0000`)) {
        const target = `${conversationId}\u0000${id.slice(canonical.length + 1)}`;
        this.messageListeners.set(target, new Set([...(this.messageListeners.get(target) ?? []), ...set]));
        this.messageListeners.delete(id);
      }
    }
    return conversationId;
  }

  private flush(canonical: string, messageId: string, extra = ""): void {
    const runtime = this.runtimes.get(canonical);
    const text = (runtime?.buffer ?? "") + extra;
    if (runtime) runtime.buffer = "";
    if (!text) return;
    const current = this.getMessage(canonical, messageId);
    if (!current || current.status !== "streaming") return;
    this.putMessage(canonical, { ...current, content: current.content + text });
  }

  private putMessage(canonical: string, message: ChatMessage): void {
    this.messageMap(canonical).set(message.id, message);
    this.notifyMessage(canonical, message.id);
  }

  private update(key: string, patch: Partial<ChatEntry>): void {
    const canonical = this.resolve(key);
    const entry = this.entries.get(canonical) ?? this.ensureEntry(canonical);
    this.entries.set(canonical, { ...entry, ...patch });
    this.notifyEntry(canonical);
  }

  private addListener(map: Map<string, Set<Listener>>, id: string, listener: Listener): () => void {
    let set = map.get(id);
    if (!set) {
      set = new Set();
      map.set(id, set);
    }
    set.add(listener);
    return () => {
      // The listener may have moved (draft → id) since it subscribed.
      for (const [key, listeners] of map) {
        if (listeners.delete(listener) && listeners.size === 0) map.delete(key);
      }
    };
  }

  private moveListeners(map: Map<string, Set<Listener>>, from: string, to: string): void {
    const moving = map.get(from);
    if (!moving) return;
    map.set(to, new Set([...(map.get(to) ?? []), ...moving]));
    map.delete(from);
  }

  private notifyEntry(canonical: string): void {
    for (const listener of [...(this.entryListeners.get(canonical) ?? [])]) listener();
  }

  private notifyMessage(canonical: string, messageId: string): void {
    for (const listener of [...(this.messageListeners.get(`${canonical}\u0000${messageId}`) ?? [])]) listener();
  }
}
