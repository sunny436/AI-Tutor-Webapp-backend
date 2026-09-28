"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { preloadMessageContent } from "@/features/markdown/lazy-message-content";
import { APP_NAME } from "@/lib/brand";
import { Announcer } from "./announcer";
import { cn } from "@v1/ui/utils";

import { useChatEntry, useConversations, useStores } from "./chat-context";
import { Composer } from "./composer";
import { MessageList, isEmptyChat } from "./message-list";

/**
 * The chat screen, for both `/` (a new chat) and `/c/[conversationId]`.
 *
 * Rendered by the `(chat)` LAYOUT, not by the two pages, so it stays mounted when
 * a new chat receives its id and the URL changes from `/` to `/c/<id>`: focus,
 * scroll position and the live stream carry straight on.
 *
 * While the chat is empty, a spacer below the composer takes as much room as the transcript
 * above it, so the ONE composer sits in the middle with the greeting just above; when the first
 * message goes, the spacer's share shrinks to nothing and the same composer glides to the bottom
 * (no second composer, no remount: the text, focus and stream are untouched). Reduced motion
 * (the device's or the app's) makes the move immediate (globals.css).
 */
export function ChatView() {
  const params = useParams<{ conversationId?: string }>();
  const conversationId = params?.conversationId ?? null;
  const { chat } = useStores();
  const [draftKey, setDraftKey] = useState(() => chat.freshDraftKey());
  const scrollRef = useRef<HTMLDivElement>(null);

  // Fetch the reply renderer now, alongside the messages, not when the first
  // reply needs it.
  useEffect(() => preloadMessageContent(), []);

  // Arriving at "/" after the held draft has been used ("New chat"): take a fresh one.
  useEffect(() => {
    if (!conversationId) setDraftKey(chat.freshDraftKey());
  }, [conversationId, chat]);

  const chatKey = conversationId ?? draftKey;

  useEffect(() => {
    chat.activeKey = chat.resolve(chatKey);
    if (conversationId) void chat.ensureLoaded(conversationId);
  }, [chat, chatKey, conversationId]);

  useDocumentTitle(conversationId);
  const empty = isEmptyChat(useChatEntry(chatKey));

  return (
    <div className="relative isolate flex h-full min-h-0 flex-col">
      {/* A faint warmth in the corners while the chat is empty (globals.css `.empty-atmosphere`). */}
      <div
        aria-hidden
        className={cn(
          "empty-atmosphere pointer-events-none absolute inset-0 -z-10 transition-opacity duration-slow ease-standard [@media(max-height:599px)]:hidden",
          empty ? "opacity-100" : "opacity-0",
        )}
      />
      <MessageList chatKey={chatKey} scrollRef={scrollRef} />
      <Composer
        chatKey={chatKey}
        onSent={() => {
          // Sending re-attaches the view to the bottom.
          const element = scrollRef.current;
          if (element) element.scrollTo({ top: element.scrollHeight });
        }}
      />
      <div
        aria-hidden
        data-composer-spacer=""
        className={cn(
          "min-h-0 shrink-0 basis-0 transition-[flex-grow] duration-slow ease-standard",
          empty ? "grow" : "grow-0",
        )}
      />
      <Announcer chatKey={chatKey} />
    </div>
  );
}

function useDocumentTitle(conversationId: string | null) {
  const { items } = useConversations();
  const entry = useChatEntry(conversationId ?? "");
  const title = conversationId ? items.find((item) => item.id === conversationId)?.title : null;
  useEffect(() => {
    if (entry?.status === "not_found") document.title = `Chat not found · ${APP_NAME}`;
    else document.title = title ? `${title} · ${APP_NAME}` : `New chat · ${APP_NAME}`;
  }, [title, entry?.status]);
}
