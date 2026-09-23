/** Conversation list, history and management. The server owns all of it. */

import { callRoute } from "./http";
import type { Conversation, ConversationPage, MessagePage } from "./types";

/** Newest activity first. The backend caps `limit` at 100. */
export function listConversations(
  options: { limit?: number; cursor?: string | null; signal?: AbortSignal } = {},
): Promise<ConversationPage> {
  return callRoute("GET /v1/conversations", {
    query: { limit: options.limit ?? 30, cursor: options.cursor },
    signal: options.signal,
  });
}

export function getConversation(id: string, signal?: AbortSignal): Promise<Conversation> {
  return callRoute("GET /v1/conversations/{conversation_id}", {
    params: { conversation_id: id },
    signal,
  });
}

export function renameConversation(id: string, title: string): Promise<Conversation> {
  return callRoute("PATCH /v1/conversations/{conversation_id}", {
    params: { conversation_id: id },
    body: { title },
  });
}

/** Messages and feedback are deleted with it. */
export function deleteConversation(id: string): Promise<void> {
  return callRoute("DELETE /v1/conversations/{conversation_id}", {
    params: { conversation_id: id },
  });
}

/**
 * Oldest first within the page. `before` (the previous page's `nextCursor`) loads
 * older messages. The backend caps `limit` at 200.
 */
export function listMessages(
  id: string,
  options: { limit?: number; before?: string | null; signal?: AbortSignal } = {},
): Promise<MessagePage> {
  return callRoute("GET /v1/conversations/{conversation_id}/messages", {
    params: { conversation_id: id },
    query: { limit: options.limit ?? 50, before: options.before },
    signal: options.signal,
  });
}
