"use client";

import { Button } from "@v1/ui/button";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { ArrowDown, MessageSquareOff } from "lucide-react";
import Link from "next/link";
import { useRef } from "react";

import { describeCode } from "@/lib/api/errors";
import { useChatEntry, useStores } from "./chat-context";
import type { ChatEntry } from "./chat-store";
import { ChatEmptyState } from "./empty-state";
import { MessageRow } from "./message";
import { useStickToBottom } from "./use-stick-to-bottom";

/** A chat with nothing in it yet (a new chat): the greeting shows, and the composer is centred. */
export function isEmptyChat(entry: ChatEntry | undefined): boolean {
  return (entry?.status ?? "idle") === "ready" && (entry?.order.length ?? 0) === 0;
}

/**
 * The scrolling transcript. Subscribes to the conversation's `order` and status
 * only — never to message content — so streaming does not re-render it.
 */
export function MessageList({ chatKey, scrollRef }: { chatKey: string; scrollRef: React.RefObject<HTMLDivElement> }) {
  const { chat } = useStores();
  const entry = useChatEntry(chatKey);
  const contentRef = useRef<HTMLDivElement>(null);
  const resolvedKey = chat.resolve(chatKey);
  const { atBottom, scrollToBottom, release } = useStickToBottom(scrollRef, contentRef, resolvedKey);

  const order = entry?.order ?? [];
  const status = entry?.status ?? "idle";

  const loadOlder = async () => {
    const element = scrollRef.current;
    if (!element || !entry?.conversationId) return;
    // Keep the reader's place: growth above the viewport must not move what they see.
    release();
    const before = element.scrollHeight - element.scrollTop;
    await chat.loadOlder(entry.conversationId);
    requestAnimationFrame(() => {
      element.scrollTop = element.scrollHeight - before;
    });
  };

  let body: React.ReactNode;
  if (status === "not_found") {
    body = (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
        <span aria-hidden className="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-surface-2 text-text-secondary">
          <MessageSquareOff className="h-6 w-6" />
        </span>
        <h2 className="font-display text-xl font-bold text-foreground">This chat isn't available</h2>
        <p className="mt-1 max-w-sm text-sm text-text-secondary">It may have been deleted, or it belongs to another account.</p>
        <Button asChild size="sm" className="mt-4">
          <Link href="/">Start a new chat</Link>
        </Button>
      </div>
    );
  } else if (status === "error" && order.length === 0) {
    const description = describeCode(entry?.loadError?.code, entry?.loadError?.requestId);
    body = (
      <div role="alert" className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
        <h2 className="font-display text-xl font-bold text-foreground">{description.title}</h2>
        <p className="mt-1 max-w-sm text-sm text-text-secondary">{description.message}</p>
        {entry?.conversationId && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-4"
            onClick={() => entry.conversationId && void chat.reload(entry.conversationId)}
          >
            Try again
          </Button>
        )}
      </div>
    );
  } else if ((status === "loading" || status === "idle") && order.length === 0) {
    body = (
      <SkeletonGroup label="Loading conversation" className="mx-auto w-full max-w-3xl space-y-8 px-4 py-8 sm:px-6">
        <Skeleton className="ml-auto h-10 w-2/5 rounded-2xl" />
        <Skeleton className="h-24 w-4/5 rounded-2xl" />
        <Skeleton className="ml-auto h-10 w-1/3 rounded-2xl" />
      </SkeletonGroup>
    );
  } else if (isEmptyChat(entry)) {
    body = <ChatEmptyState />;
  } else {
    body = (
      <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-8 sm:px-6">
        {entry?.nextCursor && (
          <div className="flex justify-center">
            <Button type="button" variant="ghost" size="sm" onClick={loadOlder} disabled={entry.loadingOlder}>
              {entry.loadingOlder ? "Loading…" : "Load earlier messages"}
            </Button>
          </div>
        )}
        {order.map((id, index) => (
          <MessageRow key={id} chatKey={chatKey} messageId={id} isLast={index === order.length - 1} />
        ))}
      </div>
    );
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <section ref={contentRef} aria-label="Conversation" className="flex min-h-full flex-col">
          {body}
        </section>
      </div>
      {!atBottom && order.length > 0 && (
        <button
          type="button"
          onClick={() => scrollToBottom("smooth")}
          className="focus-ring absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-semibold text-brand elev-2 transition hover:bg-brand-soft motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-left-1/2 motion-safe:slide-in-from-bottom-1 duration-base ease-enter"
        >
          <ArrowDown aria-hidden className="h-3.5 w-3.5" />
          Jump to latest
        </button>
      )}
    </div>
  );
}
