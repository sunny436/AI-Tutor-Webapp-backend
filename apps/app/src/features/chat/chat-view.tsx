"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { preloadMessageContent } from "@/features/markdown/lazy-message-content";
import { APP_NAME } from "@/lib/brand";
import { Announcer } from "./announcer";
import { useChatEntry, useConversations, useStores } from "./chat-context";
import { Composer } from "./composer";
import { MessageList } from "./message-list";

/**
 * The chat screen, for both `/` (a new chat) and `/c/[conversationId]`.
 *
 * Rendered by the `(chat)` LAYOUT, not by the two pages, so it stays mounted when
 * a new chat receives its id and the URL changes from `/` to `/c/<id>`: focus,
 * scroll position and the live stream carry straight on.
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <MessageList chatKey={chatKey} scrollRef={scrollRef} />
      <Composer
        chatKey={chatKey}
        onSent={() => {
          // Sending re-attaches the view to the bottom.
          const element = scrollRef.current;
          if (element) element.scrollTo({ top: element.scrollHeight });
        }}
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
