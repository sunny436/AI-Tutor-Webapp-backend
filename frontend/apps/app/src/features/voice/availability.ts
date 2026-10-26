"use client";

import { useEffect, useState } from "react";

import { getVoice } from "@/lib/api/voice";
import type { VoiceAvailability } from "@/lib/api/types";
import { canDoVoice } from "./audio-unlock";

/** Asked once per page: the API says whether voice mode is for this student (it checks every voice request too). */
let offered: Promise<VoiceAvailability> | null = null;

/** What the API offers this student (voice mode, the spoken acknowledgement); asked once per page. */
export function voiceConfig(): Promise<VoiceAvailability> {
  offered ??= getVoice().catch(() => {
    offered = null; // asked again on the next chat screen
    return { enabled: false };
  });
  return offered;
}

/** Whether to show the Voice button: offered by the API, and this browser can capture, record and play. */
export function useVoiceOffered(): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!canDoVoice()) return;
    let alive = true;
    void voiceConfig().then((voice) => alive && setShown(voice.enabled));
    return () => {
      alive = false;
    };
  }, []);
  return shown;
}
