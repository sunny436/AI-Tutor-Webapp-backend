"use client";

import { useEffect, useRef, useState } from "react";

import { describeCode } from "@/lib/api/errors";
import { useChatEntry, useStores } from "./chat-context";
import { plainText } from "./plain-text";

/**
 * What a screen reader hears about the conversation.
 *
 * One polite status region, announced at the moments that matter — not per token
 * (a live region over streaming text would re-read the reply on every chunk):
 *
 *   reply starts   "Assistant is responding"
 *   reply ends     the reply itself, as plain text (first ~1,000 characters; the full
 *                  reply is on the page to navigate)
 *   stopped/failed "Response stopped" / the error's title
 */
export function Announcer({ chatKey }: { chatKey: string }) {
  const { chat } = useStores();
  const entry = useChatEntry(chatKey);
  const phase = entry?.stream?.phase ?? null;
  // Which conversation (after resolving a draft's alias) and phase we last saw.
  const previous = useRef({ key: chat.resolve(chatKey), phase });
  const [text, setText] = useState("");

  useEffect(() => {
    const key = chat.resolve(chatKey);
    const before = previous.current;
    previous.current = { key, phase };
    if (before.key !== key) {
      // Switched to another conversation: start quiet.
      setText("");
      return;
    }
    if (!before.phase && phase) {
      setText("Assistant is responding");
      return;
    }
    if (before.phase && !phase) {
      const id = chat.lastAssistantId(chatKey);
      const message = id ? chat.getMessage(chatKey, id) : undefined;
      if (!message) return;
      if (message.status === "cancelled") setText("Response stopped");
      else if (message.status === "error") setText(describeCode(message.failure?.code).title);
      else setText(plainText(message.content));
    }
  }, [phase, chat, chatKey]);

  return (
    <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {text}
    </div>
  );
}
