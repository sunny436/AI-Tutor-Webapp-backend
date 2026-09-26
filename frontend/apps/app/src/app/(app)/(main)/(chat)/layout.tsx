import type { ReactNode } from "react";

import { ChatView } from "@/features/chat/chat-view";

/**
 * `/` and `/c/[conversationId]` share this layout, and the chat lives HERE rather
 * than in the pages. Next.js keeps a layout mounted when navigating between its
 * pages, so when a new chat gets its id and the URL moves from `/` to `/c/<id>`,
 * nothing remounts: the stream, scroll position and focus carry on.
 */
export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <ChatView />
      {children}
    </>
  );
}
