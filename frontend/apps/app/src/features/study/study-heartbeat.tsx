"use client";

import { useCallback } from "react";

import { useStores } from "@/features/chat/chat-context";
import { useStudyBeat } from "./use-study-beat";

/** Study time (Study Activity): this tab's observations, once for the whole signed-in app. */
export function StudyHeartbeat() {
  const { chat } = useStores();
  useStudyBeat(useCallback(() => chat.anyStreaming(), [chat]));
  return null;
}
