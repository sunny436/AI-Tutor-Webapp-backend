"use client";

import { Button } from "@v1/ui/button";
import { cn } from "@v1/ui/utils";
import { memo } from "react";

import { BrandMark } from "@/components/brand/brand-mark";
import { MessageContent } from "@/features/markdown/lazy-message-content";
import type { ChatMessage } from "./chat-store";
import { useChatEntry, useChatMessage, useStores } from "./chat-context";
import { ErrorMessage } from "./error-message";
import { MessageActions } from "./message-actions";
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

export function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <article aria-label="You" className="flex justify-end">
      <div
        className={cn(
          "min-w-0 max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-surface-2 px-4 py-2.5 text-[0.9375rem] leading-relaxed text-foreground sm:max-w-[75%]",
          message.pending && "opacity-80",
        )}
      >
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
  // Streaming on the server, but not from this tab: another tab is writing it.
  const elsewhere = streaming && !live;
  const retry =
    canRegenerate && message.conversationId ? () => void chat.regenerate(message.conversationId) : undefined;

  return (
    <article aria-label="Assistant" aria-busy={streaming} className="group flex gap-3">
      <BrandMark size={28} className="mt-0.5 rounded-lg" />
      <div className="min-w-0 flex-1">
        {(message.content || (live && streaming) || phase === "stopping" || message.status === "cancelled" || elsewhere) && (
          <div className="w-fit max-w-full pt-0.5">
            {message.content ? (
              <>
                <MessageContent content={message.content} />
                {live && streaming && <StreamingCaret />}
              </>
            ) : live && streaming ? (
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
