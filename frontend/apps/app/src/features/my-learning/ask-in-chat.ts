"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { useStores } from "@/features/chat/chat-context";

/**
 * A request goes after unsent text, on its own line, never over it; the same request is not added
 * twice (Back, then the same button again).
 */
export function withRequest(draft: string, request: string): string {
  const kept = draft.trimEnd();
  if (!kept) return request;
  return kept.split("\n").includes(request) ? kept : `${kept}\n${request}`;
}

/**
 * My Learning's "Practise" and "Revise": a new chat with the request filled in, never sent. The
 * same way the File Library's "Ask in chat" works: the request goes into the draft of the new chat
 * "/" opens with (`freshDraftKey`), which lives in memory only, so it is never in the URL and a
 * reload does not fill it again. Nothing is sent until the student presses Send.
 */
export function useAskInChat(): (request: string) => void {
  const { chat } = useStores();
  const router = useRouter();
  return useCallback(
    (request: string) => {
      const key = chat.freshDraftKey();
      chat.setDraft(key, withRequest(chat.getDraft(key), request));
      router.push("/");
    },
    [chat, router],
  );
}
