"use client";

import { Button } from "@v1/ui/button";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { ArrowDown, MessageSquareOff } from "lucide-react";
import Link from "next/link";
import { startTransition, useEffect, useRef, useState } from "react";

import { useRendererReady } from "@/features/markdown/lazy-message-content";
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
export function MessageList({ chatKey, scrollRef }: { chatKey: string; scrollRef: React.RefObject<HTMLDivElement | null> }) {
  const { chat } = useStores();
  const entry = useChatEntry(chatKey);
  const contentRef = useRef<HTMLDivElement>(null);
  const resolvedKey = chat.resolve(chatKey);
  const { atBottom, scrollToBottom, release } = useStickToBottom(scrollRef, contentRef, resolvedKey);

  const order = entry?.order ?? [];
  const status = entry?.status ?? "idle";
  // An opened chat keeps its skeleton until its replies can be drawn (never while a reply streams, and
  // never again once they are on screen), then draws them in a transition: React renders a long
  // transcript in slices, not as one long task (2.2 s opening a 50-message chat on a phone, CPU 4x).
  const rendererReady = useRendererReady();
  const [drawn, setDrawn] = useState(false);
  const live = Boolean(entry?.stream);
  const hasMessages = order.length > 0;
  useEffect(() => {
    if (drawn || !hasMessages) return;
    if (live) setDrawn(true);
    else if (rendererReady) startTransition(() => setDrawn(true));
  }, [drawn, hasMessages, live, rendererReady]);
  const drawing = drawn || live;

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
  } else if (((status === "loading" || status === "idle") && order.length === 0) || (!drawing && order.length > 0)) {
    body = (
      <SkeletonGroup label="Loading conversation" className="mx-auto w-full px-5 sm:px-6 lg:w-[min(100%,clamp(42.5rem,75%,57rem))] space-y-8 py-8">
        <Skeleton className="ml-auto h-10 w-2/5 rounded-2xl" />
        <Skeleton className="h-24 w-4/5 rounded-2xl" />
        <Skeleton className="ml-auto h-10 w-1/3 rounded-2xl" />
      </SkeletonGroup>
    );
  } else if (isEmptyChat(entry)) {
    body = <ChatEmptyState chatKey={chatKey} />;
  } else {
    body = (
      <div className="mx-auto w-full px-5 sm:px-6 lg:w-[min(100%,clamp(42.5rem,75%,57rem))] space-y-8 py-8">
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
      <div ref={scrollRef} className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]">
        <section ref={contentRef} aria-label="Conversation" className="flex min-h-full flex-col">
          {body}
        </section>
      </div>
      {/* Centred just above the composer, as before, but in the flow instead of over the transcript,
          so it never covers a message. Shown only while the reader is away from the latest. */}
      {!atBottom && order.length > 0 && (
        <div className="flex shrink-0 justify-center pt-1.5">
          <button
            type="button"
            onClick={() => scrollToBottom("smooth")}
            className="focus-ring flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-semibold text-brand elev-1 transition hover:bg-brand-soft motion-safe:animate-in motion-safe:fade-in-0 duration-base ease-enter"
          >
            <ArrowDown aria-hidden className="h-3.5 w-3.5" />
            Jump to latest
          </button>
        </div>
      )}
    </div>
  );
}
