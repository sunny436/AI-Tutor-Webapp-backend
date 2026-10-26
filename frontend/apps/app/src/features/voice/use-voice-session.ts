"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { useStores } from "@/features/chat/chat-context";
import { synthesize, transcribe } from "@/lib/api/voice";
import { takeUnlockedAudio } from "./audio-unlock";
import { voiceConfig } from "./availability";
import { VoiceSession } from "./voice-session";

/**
 * The voice session of the open voice view: started when it opens, ended when it closes, when the page is
 * hidden or left (a phone locked, a tab switched), so the microphone is never left listening unseen.
 */
export function useVoiceSession(chatKey: string) {
  const { chat } = useStores();
  const [session] = useState(
    () =>
      new VoiceSession(chat, chatKey, {
        transcribe,
        synthesize,
        getUserMedia: (constraints) => navigator.mediaDevices.getUserMedia(constraints),
        audio: () => takeUnlockedAudio() ?? new AudioContext(),
        config: voiceConfig,
      }),
  );
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);

  useEffect(() => {
    session.start();
    const leave = () => session.end();
    const hidden = () => document.visibilityState === "hidden" && session.end();
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pagehide", leave);
      document.removeEventListener("visibilitychange", hidden);
      session.end();
    };
  }, [session]);

  return { ...snapshot, session };
}
