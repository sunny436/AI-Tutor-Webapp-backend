import { notFound } from "next/navigation";

import { isUuid } from "@/lib/api/routes";

/**
 * `/c/<id>` — an existing chat, rendered by the `(chat)` layout's ChatView.
 * Conversation ids are UUIDs; anything else is a 404 before any request is made.
 * (A well-formed id that is missing, or not yours, is handled in the chat view:
 * the API answers 404 either way.)
 */
export default async function ConversationPage({ params }: { params: Promise<{ conversationId: string }> }) {
  if (!isUuid((await params).conversationId)) notFound();
  return null;
}
