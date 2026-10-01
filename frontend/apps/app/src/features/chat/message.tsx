"use client";

import { Button } from "@v1/ui/button";
import { cn } from "@v1/ui/utils";
import { type CSSProperties, memo, useMemo, useState } from "react";

import { BrandMark } from "@/components/brand/brand-mark";
import { FileKindIcon } from "@/features/files/attachment-chip";
import { fileTypeOf } from "@/lib/api/files";
import type { TestState } from "@/features/markdown/context";
import { MessageContent, needsFullWidth } from "@/features/markdown/lazy-message-content";
import type { ChatMessage } from "./chat-store";
import { useChatEntry, useChatMessage, useStores } from "./chat-context";
import { ErrorMessage } from "./error-message";
import { MessageActions } from "./message-actions";
import { useSmoothText } from "./smooth-text";
import { StreamingCaret, StreamingIndicator } from "./streaming-indicator";

/**
 * One row of the transcript. Subscribes to its own message only, so a streamed
 * token re-renders this row and no other.
 */
export const MessageRow = memo(function MessageRow({
  chatKey,
  messageId,
  isLast,
}: {
  chatKey: string;
  messageId: string;
  isLast: boolean;
}) {
  const message = useChatMessage(chatKey, messageId);
  if (!message) return null;
  if (message.role === "user") return <UserMessage message={message} />;
  return isLast ? (
    <LastAssistantMessage chatKey={chatKey} message={message} />
  ) : (
    <AssistantMessage chatKey={chatKey} message={message} live={false} phase={null} canRegenerate={false} />
  );
});

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

/**
 * When a message was written, as a clock time. Fixed once rendered — a label
 * that ticks ("1 min ago") would re-render messages that are not streaming.
 */
function MessageTime({ value, className }: { value: string; className?: string }) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return (
    <time dateTime={value} className={cn("mt-1.5 block text-right text-2xs", className)}>
      {timeFormat.format(date)}
    </time>
  );
}

/** The rise-in's length: --motion-base. */
const ARRIVAL_MS = 220;
/** When each message began to arrive, for this page's lifetime. */
const arrivals = new Map<string, number>();
let lastSent: { content: string; at: number } | null = null;

/**
 * A message rises in once, when it first appears live: the student's as it is sent, a reply
 * as it starts. The same message mounting again (its optimistic id swapped for the server's,
 * the chat moving to its own address) continues that one arrival rather than starting another
 * or snapping into place; history never animates. The style is the negative delay that does it.
 */
function useArrival(id: string, start: "sent" | "confirmed" | "live" | null, content = ""): CSSProperties | undefined {
  const [style] = useState<CSSProperties | undefined>(() => {
    if (typeof window === "undefined" || start === null) return undefined;
    const now = performance.now();
    if (start === "sent" && !arrivals.has(id)) {
      arrivals.set(id, now);
      lastSent = { content, at: now };
    }
    if (start === "confirmed" && lastSent?.content === content) {
      arrivals.set(id, lastSent.at);
      lastSent = null;
    }
    if (start === "live" && !arrivals.has(id)) arrivals.set(id, now);
    const began = arrivals.get(id);
    if (began === undefined || now - began >= ARRIVAL_MS) return undefined;
    return { animationDelay: `${-Math.round(now - began)}ms` };
  });
  return style;
}

export function UserMessage({ message }: { message: ChatMessage }) {
  const arrival = useArrival(message.id, message.pending ? "sent" : "confirmed", message.content);
  return (
    <article aria-label="You" className={cn("flex justify-end", arrival && "animate-rise-in")} style={arrival}>
      <div
        className={cn(
          "min-w-0 max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-surface-2 px-4 py-2.5 text-base text-foreground sm:max-w-[75%]",
          message.pending && "opacity-80",
        )}
      >
        {message.attachments?.length ? (
          <ul aria-label="Attached files" className="mb-1.5 flex flex-wrap gap-1.5 whitespace-normal">
            {message.attachments.map((attachment, index) => (
              <li
                key={`${attachment.fileId ?? "deleted"}-${index}`}
                className="flex max-w-[14rem] items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-1 text-xs"
              >
                <FileKindIcon
                  kind={fileTypeOf(attachment.filename)?.kind ?? null}
                  className="h-3.5 w-3.5 shrink-0 text-text-secondary"
                />
                <span className="truncate font-semibold">{attachment.filename}</span>
                {attachment.fileId === null && <span className="shrink-0 text-text-secondary">(deleted)</span>}
              </li>
            ))}
          </ul>
        ) : null}
        {message.content}
        <MessageTime value={message.createdAt} className="text-text-secondary" />
      </div>
    </article>
  );
}

/** The latest reply also watches the conversation's stream (stop, regenerate). */
function LastAssistantMessage({ chatKey, message }: { chatKey: string; message: ChatMessage }) {
  const entry = useChatEntry(chatKey);
  const live = entry?.stream?.assistantId === message.id;
  return (
    <AssistantMessage
      chatKey={chatKey}
      message={message}
      live={live}
      phase={live ? (entry?.stream?.phase ?? null) : null}
      canRegenerate={!entry?.stream && Boolean(message.conversationId)}
    />
  );
}

function AssistantMessage({
  chatKey,
  message,
  live,
  phase,
  canRegenerate,
}: {
  chatKey: string;
  message: ChatMessage;
  live: boolean;
  phase: string | null;
  canRegenerate: boolean;
}) {
  const { chat } = useStores();
  const streaming = message.status === "streaming";
  const revealing = live && streaming;
  const assessments = message.metadata?.assessments;
  const testError = message.metadata?.assessmentError?.code ?? null;
  const testNotice = message.testNotice ?? null;
  // The reply's practice test as the server recorded it: its card draws only this.
  const tests = useMemo<TestState>(
    () => ({
      streaming,
      assessments: assessments ?? [],
      error: testError,
      notice: testNotice,
      respond: (position, request) => chat.respondToTest(chatKey, message.id, position, request),
    }),
    [chat, chatKey, message.id, streaming, assessments, testError, testNotice],
  );
  // The reply as it should read now: at an even pace while it streams (smooth-text.ts).
  const text = useSmoothText(message.content, revealing);
  const arrival = useArrival(message.id, revealing ? "live" : null);
  // Streaming on the server, but not from this tab: another tab is writing it.
  const elsewhere = streaming && !live;
  const retry =
    canRegenerate && message.conversationId ? () => void chat.regenerate(message.conversationId) : undefined;

  return (
    <article
      aria-label="Assistant"
      aria-busy={streaming}
      className={cn("group flex gap-3", arrival && "animate-rise-in")}
      style={arrival}
    >
      <BrandMark size={28} className="mt-0.5 rounded-lg" />
      <div className="min-w-0 flex-1">
        {(text || revealing || phase === "stopping" || message.status === "cancelled" || elsewhere) && (
          <div className={cn("max-w-full pt-0.5", needsFullWidth(text) ? "w-full" : "w-fit")}>
            {text ? (
              <>
                <MessageContent
                  content={text}
                  streaming={revealing}
                  // A finished reply without citations has none (not "not known yet").
                  citations={message.metadata?.citations ?? (streaming ? undefined : [])}
                  tests={tests}
                />
                {revealing && <StreamingCaret />}
              </>
            ) : revealing ? (
              <StreamingIndicator />
            ) : null}

            {phase === "stopping" && <p className="mt-1 text-2xs text-text-secondary">Stopping…</p>}
            {message.status === "cancelled" && <p className="mt-1 text-2xs font-medium text-text-secondary">Stopped</p>}
            {elsewhere && (
              <div className="mt-1 flex items-center gap-2 text-2xs text-text-secondary">
                <span>Still being written in another tab.</span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-2xs"
                  onClick={() => message.conversationId && void chat.reload(message.conversationId)}
                >
                  Refresh
                </Button>
              </div>
            )}
            {!streaming && message.content && <MessageTime value={message.createdAt} className="text-text-secondary" />}
          </div>
        )}
        {message.status === "error" && (
          <ErrorMessage
            code={message.failure?.code ?? (message.metadata?.errorCode === "interrupted" ? "interrupted" : "internal_error")}
            requestId={message.failure?.requestId}
            onRetry={message.failure?.retryable === false ? undefined : retry}
            retryLabel="Regenerate"
          />
        )}
        {!streaming && message.status !== "error" && (
          <MessageActions chatKey={chatKey} message={message} canRegenerate={canRegenerate} alwaysVisible={canRegenerate} />
        )}
      </div>
    </article>
  );
}
