"use client";

import { useCallback } from "react";

import { useStores } from "@/features/chat/chat-context";
import { useActivityHeartbeat } from "./use-activity-heartbeat";

/** Active time in PadhAI (Settings > Progress & Goals): one heartbeat for the whole signed-in app. */
export function ActivityHeartbeat() {
  const { chat } = useStores();
  useActivityHeartbeat(useCallback(() => chat.anyStreaming(), [chat]));
  return null;
}
