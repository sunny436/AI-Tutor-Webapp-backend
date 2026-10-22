"use client";

/**
 * Creates the chat and conversation-list stores once per signed-in session and
 * wires them together. Mounted by the app shell, so it survives navigation
 * between chats and Settings — which is what lets a reply keep streaming while
 * the user looks elsewhere.
 */

import { useRouter } from "next/navigation";
import { type ReactNode, createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";

import {
  cancelMessage,
  clearFeedback,
  respondToAssessment,
  setFeedback,
  streamChat,
  streamRegenerate,
} from "@/lib/api/chat";
import { findFile, getFile, retryFile, sha256Hex, uploadFile } from "@/lib/api/files";
import { deleteConversation, listConversations, listMessages, renameConversation } from "@/lib/api/conversations";
import { retargetAppPath } from "@/features/navigation/app-return";
import { leaving } from "@/features/navigation/leaving";
import { fromAnswer, fromReply } from "@/features/streak/celebrations/queue";
import { CELEBRATE_EVENT, LEARNING_EVENT } from "@/lib/activity";
import { FALLBACK_GREETING } from "@/lib/greeting";
import { onUnauthorized } from "@/lib/api/http";
import type { ConversationPage } from "@/lib/api/types";
import { ConversationsStore, type ConversationsState } from "@/features/conversations/conversations-store";
import { AttachmentStore, type Chip } from "@/features/files/attachment-store";
import { StorageFullDialog } from "@/features/files/storage-full-dialog";
import { type ChatEntry, type ChatMessage, ChatStore } from "./chat-store";

type Stores = { chat: ChatStore; conversations: ConversationsStore; attachments: AttachmentStore };

const ChatContext = createContext<Stores | null>(null);
/** This week's study greetings, loaded with the page by the signed-in layout (lib/greeting.ts). */
const GreetingContext = createContext<readonly string[]>([FALLBACK_GREETING]);
const FALLBACK_POOL = [FALLBACK_GREETING];

/** Opens the "Storage full" dialog (an upload anywhere can be refused for storage). */
const StorageFullContext = createContext<() => void>(() => {});

/** How often the sidebar may refetch when the window regains focus. */
const FOCUS_REFRESH_MS = 30_000;

export function ChatProvider({
  initialConversations,
  greetings = FALLBACK_POOL,
  children,
}: {
  initialConversations: ConversationPage | null;
  greetings?: readonly string[];
  children: ReactNode;
}) {
  const router = useRouter();
  const [storageFull, setStorageFull] = useState(false);
  const [showStorageFull] = useState(() => () => setStorageFull(true));
  const [stores] = useState<Stores>(() => {
    const chat = new ChatStore({
      api: {
        streamChat,
        streamRegenerate,
        cancelMessage,
        listMessages,
        setFeedback,
        clearFeedback,
        deleteConversation,
        respondToAssessment,
      },
    });
    return {
      conversations: new ConversationsStore({ listConversations, renameConversation }, initialConversations),
      chat,
      // Keyed like the chat store: a draft and the conversation it becomes share their files.
      attachments: new AttachmentStore({ sha256Hex, findFile, uploadFile, getFile, retryFile }, (key) =>
        chat.resolve(key),
      ),
    };
  });

  useEffect(() => {
    const { chat, conversations } = stores;
    if (!initialConversations) void conversations.refresh();

    chat.onConversationCreated = (conversation, draftKey) => {
      stores.attachments.rekey(draftKey, conversation.id);
      conversations.upsert(conversation);
      if (chat.activeKey !== conversation.id) return;
      const path = `/c/${conversation.id}`;
      // "Close settings" comes back to this chat, however the next lines go (a replace below can
      // itself be overtaken by a click that follows it).
      retargetAppPath("/", path);
      // Still looking at the draft, and not already on the way elsewhere? Give it its URL. The URL
      // alone can't tell: while Next loads the next page (Settings, on a slow server) it still says
      // "/", and a replace now would overtake that navigation and bring the student back here.
      // Both URLs render the same persistent chat view, so nothing remounts.
      if (window.location.pathname === "/" && leaving.current() === null) router.replace(path);
    };
    chat.onConversationUpdated = (conversation) => conversations.upsert(conversation);
    chat.onReplyFinished = (done) => {
      window.dispatchEvent(new Event(LEARNING_EVENT));
      // This answer made its day a learning day (the server says so once): celebrate it.
      if (done.learning) {
        window.dispatchEvent(new CustomEvent(CELEBRATE_EVENT, { detail: fromReply(done.learning, done.message.id) }));
      }
    };
    // A practice answer (bank answers count in fives): the same again.
    chat.onPracticeAnswered = (learning, messageId, answered) => {
      window.dispatchEvent(new Event(LEARNING_EVENT));
      if (learning) {
        window.dispatchEvent(new CustomEvent(CELEBRATE_EVENT, { detail: fromAnswer(learning, messageId, answered) }));
      }
    };
    chat.onSendRefused = (key, attachments) => stores.attachments.restore(key, attachments);
    stores.attachments.onStorageFull = () => setStorageFull(true);

    // Any API call answered with "your session is gone": stop everything and sign in.
    const offUnauthorized = onUnauthorized(() => {
      chat.reset();
      const redirect = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/login?reason=expired&redirect=${encodeURIComponent(redirect)}`);
    });

    // A chat started or renamed in another tab shows up when this one is focused.
    const onFocus = () => {
      void conversations.refresh(FOCUS_REFRESH_MS);
      stores.attachments.refreshReading();
    };
    window.addEventListener("focus", onFocus);

    return () => {
      offUnauthorized();
      window.removeEventListener("focus", onFocus);
      chat.onConversationCreated = undefined;
      chat.onConversationUpdated = undefined;
      chat.onReplyFinished = undefined;
      chat.onPracticeAnswered = undefined;
      chat.onSendRefused = undefined;
      stores.attachments.onStorageFull = undefined;
    };
  }, [stores, router, initialConversations]);

  return (
    <ChatContext.Provider value={stores}>
      <StorageFullContext.Provider value={showStorageFull}>
        <GreetingContext.Provider value={greetings}>{children}</GreetingContext.Provider>
        <StorageFullDialog open={storageFull} onOpenChange={setStorageFull} />
      </StorageFullContext.Provider>
    </ChatContext.Provider>
  );
}

export function useShowStorageFull(): () => void {
  return useContext(StorageFullContext);
}

/** The lines a new chat's greeting is picked from: this week's pool, the same for everyone. */
export function useStudyGreetings(): readonly string[] {
  return useContext(GreetingContext);
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

/** The files attached to one chat's unsent message. */
export function useAttachments(key: string): readonly Chip[] {
  const { attachments } = useStores();
  return useSyncExternalStore(
    (listener) => attachments.subscribe(key, listener),
    () => attachments.get(key),
    () => attachments.get(key),
  );
}

export function useConversations(): ConversationsState {
  const { conversations } = useStores();
  return useSyncExternalStore(conversations.subscribe, conversations.getSnapshot, conversations.getSnapshot);
}
