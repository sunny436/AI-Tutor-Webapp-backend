"use client";

import { useEffect } from "react";

import { reportActivity } from "@/lib/api/progress";
import { ACTIVITY_EVENT, REPORT_EVERY_MS, shouldReport } from "@/lib/activity";

const INTERACTIONS = ["pointerdown", "keydown", "wheel", "touchstart", "scroll"] as const;

/**
 * Reports active minutes while the student uses PadhAI (lib/activity.ts has the rule). Mounted
 * once, in the signed-in app shell. A failed report is simply not counted: nothing retries it.
 */
export function useActivityHeartbeat(isStreaming: () => boolean): void {
  useEffect(() => {
    let lastInteraction = Date.now(); // opening a page is using it
    const touch = () => {
      lastInteraction = Date.now();
    };
    for (const name of INTERACTIONS) window.addEventListener(name, touch, { passive: true, capture: true });

    const timer = window.setInterval(() => {
      const report = shouldReport({
        visible: document.visibilityState === "visible",
        now: Date.now(),
        lastInteraction,
        streaming: isStreaming(),
      });
      if (!report) return;
      reportActivity()
        .then((result) => {
          if (result?.credited) window.dispatchEvent(new Event(ACTIVITY_EVENT));
        })
        .catch(() => undefined);
    }, REPORT_EVERY_MS);

    return () => {
      window.clearInterval(timer);
      for (const name of INTERACTIONS) window.removeEventListener(name, touch, { capture: true });
    };
  }, [isStreaming]);
}
