"use client";

import { useEffect, useState } from "react";

import { getVoice } from "@/lib/api/voice";
import { canDoVoice } from "./audio-unlock";

/** Asked once per page: the API says whether voice mode is for this student (it checks every voice request too). */
let offered: Promise<boolean> | null = null;

/** Whether to show the Voice button: offered by the API, and this browser can capture, record and play. */
export function useVoiceOffered(): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!canDoVoice()) return;
    let alive = true;
    offered ??= getVoice()
      .then((voice) => voice.enabled)
      .catch(() => {
        offered = null; // asked again on the next chat screen
        return false;
      });
    void offered.then((enabled) => alive && setShown(enabled));
    return () => {
      alive = false;
    };
  }, []);
  return shown;
}
