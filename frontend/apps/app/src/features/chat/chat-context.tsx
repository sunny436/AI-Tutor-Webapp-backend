"use client";

/**
 * Creates the chat and conversation-list stores once per signed-in session and
 * wires them together. Mounted by the app shell, so it survives navigation
 * between chats and Settings — which is what lets a reply keep streaming while
 * the user looks elsewhere.
 */

import { useRouter } from "next/navigation";
import { type ReactNode, createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";

import { cancelMessage, clearFeedback, setFeedback, streamChat, streamRegenerate } from "@/lib/api/chat";
import { deleteConversation, listConversations, listMessages, renameConversation } from "@/lib/api/conversations";
import { onUnauthorized } from "@/lib/api/http";
import type { ConversationPage } from "@/lib/api/types";
import { ConversationsStore, type ConversationsState } from "@/features/conversations/conversations-store";
import { type ChatEntry, type ChatMessage, ChatStore } from "./chat-store";

type Stores = { chat: ChatStore; conversations: ConversationsStore };

const ChatContext = createContext<Stores | null>(null);

/** How often the sidebar may refetch when the window regains focus. */
const FOCUS_REFRESH_MS = 30_000;

export function ChatProvider({
  initialConversations,
  children,
}: {
  initialConversations: ConversationPage | null;
  children: ReactNode;
}) {
  const router = useRouter();
  const [stores] = useState<Stores>(() => ({
    conversations: new ConversationsStore({ listConversations, renameConversation }, initialConversations),
    chat: new ChatStore({
      api: { streamChat, streamRegenerate, cancelMessage, listMessages, setFeedback, clearFeedback, deleteConversation },
    }),
  }));

  useEffect(() => {
    const { chat, conversations } = stores;
    if (!initialConversations) void conversations.refresh();

    chat.onConversationCreated = (conversation) => {
      conversations.upsert(conversation);
      // Still looking at the draft that became this conversation? Give it its URL.
      // Both URLs render the same persistent chat view, so nothing remounts.
      if (chat.activeKey === conversation.id && window.location.pathname === "/") {
        router.replace(`/c/${conversation.id}`);
      }
    };
    chat.onConversationUpdated = (conversation) => conversations.upsert(conversation);

    // Any API call answered with "your session is gone": stop everything and sign in.
    const offUnauthorized = onUnauthorized(() => {
      chat.reset();
      const redirect = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/login?reason=expired&redirect=${encodeURIComponent(redirect)}`);
    });

    // A chat started or renamed in another tab shows up when this one is focused.
    const onFocus = () => void conversations.refresh(FOCUS_REFRESH_MS);
    window.addEventListener("focus", onFocus);

    return () => {
      offUnauthorized();
      window.removeEventListener("focus", onFocus);
      chat.onConversationCreated = undefined;
      chat.onConversationUpdated = undefined;
    };
  }, [stores, router, initialConversations]);

  return <ChatContext.Provider value={stores}>{children}</ChatContext.Provider>;
}

export function useStores(): Stores {
  const stores = useContext(ChatContext);
  if (!stores) throw new Error("useStores must be used inside <ChatProvider>");
  return stores;
}

/** One conversation's entry (order, status, stream) — not its messages. */
export function useChatEntry(key: string): ChatEntry | undefined {
  const { chat } = useStores();
  return useSyncExternalStore(
    (listener) => chat.subscribe(key, listener),
    () => chat.getEntry(key),
    () => chat.getEntry(key),
  );
}

/** One message. Re-renders only when that message changes. */
export function useChatMessage(key: string, messageId: string): ChatMessage | undefined {
  const { chat } = useStores();
  return useSyncExternalStore(
    (listener) => chat.subscribeMessage(key, messageId, listener),
    () => chat.getMessage(key, messageId),
    () => chat.getMessage(key, messageId),
  );
}

export function useConversations(): ConversationsState {
  const { conversations } = useStores();
  return useSyncExternalStore(conversations.subscribe, conversations.getSnapshot, conversations.getSnapshot);
}
