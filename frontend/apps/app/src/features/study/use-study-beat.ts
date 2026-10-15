"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { DEFAULT_EVENTS, useIdleTimer } from "react-idle-timer";

import { ApiError } from "@/lib/api/errors";
import { sendStudyBeat } from "@/lib/api/study";
import {
  ActivityRun,
  BEAT_EVERY_MS,
  idleTimeoutMs,
  isEligible,
  isLearningView,
  isUncertain,
  promptBeforeIdleMs,
  sendWithRetry,
} from "./study-client";
import { studyStore, useStudy } from "./study-store";

/** Input that counts as activity: the library's defaults, but visibility is ours (hidden is not idle,
 * it is not studying), and switching back to a tab must not count as input. */
const EVENTS = DEFAULT_EVENTS.filter((name) => name !== "visibilitychange");
const DEFAULT_IDLE = { readingSeconds: 300, solvingSeconds: 120 };

/**
 * This tab's study observations (study-client.ts has the rules). Mounted once in the signed-in
 * app, beside the activity heartbeat it leaves alone. Beats go every 30 s from every open tab,
 * visible or not (that is also how app time is measured), and at once on every change; one at a
 * time, so their order is the order they were observed in.
 */
export function useStudyBeat(isStreaming: () => boolean): void {
  const pathname = usePathname();
  const study = useStudy();
  const session = study.server?.session ?? null;
  const activity = session?.segment?.activity ?? "reading";
  const timeout = idleTimeoutMs(study.server?.idle ?? DEFAULT_IDLE, activity);

  const timer = useIdleTimer({
    timeout,
    promptBeforeIdle: promptBeforeIdleMs(timeout, activity),
    events: EVENTS,
    crossTab: false,
    onPrompt: () => studyStore.set({ prompting: true }),
    onIdle: () => studyStore.set({ idle: true, prompting: false }),
    onActive: () => studyStore.set({ idle: false, prompting: false }),
  });
  // The hook's object is new on every render: effects read it through a ref.
  const idleTimer = useRef(timer);
  idleTimer.current = timer;

  const [visible, setVisible] = useState(true);
  const [online, setOnline] = useState(true);
  const facts = {
    visible,
    online,
    studyView: isLearningView(pathname),
    running: session?.status === "active",
    idle: study.idle,
  };
  const current = useRef(facts);
  current.current = facts;
  const run = useRef(new ActivityRun(false));
  const inFlight = useRef<Promise<void> | null>(null);
  const again = useRef(false);

  const beat = useCallback((): Promise<void> => {
    if (inFlight.current) {
      again.current = true;
      return inFlight.current;
    }
    const loop = async () => {
      do {
        again.current = false;
        const sent = run.current.observe();
        const { studyView, visible: shown } = current.current;
        try {
          const state = await sendWithRetry(
            {
              beatId: crypto.randomUUID(),
              clientId: studyStore.clientId,
              wasActive: sent.wasActive,
              nowActive: sent.nowActive,
              studyView,
              visible: shown,
            },
            sendStudyBeat,
          );
          run.current.received(sent);
          studyStore.apply(state);
        } catch (error) {
          run.current.lost();
          if (isUncertain(error)) studyStore.set({ offline: true });
          else if (!(error instanceof ApiError && error.status === 429) && !studyStore.get().server) {
            studyStore.set({ loadError: error });
          }
        }
      } while (again.current);
    };
    inFlight.current = loop().finally(() => {
      inFlight.current = null;
    });
    return inFlight.current;
  }, []);

  // Every change of eligibility is reported at once: the edge beat closes or opens a run.
  const eligible = isEligible(facts);
  useEffect(() => {
    if (run.current.update(eligible)) void beat();
  }, [eligible, beat]);

  useEffect(() => {
    studyStore.flush = beat;
    studyStore.acted = (active) => run.current.acted(active);
    studyStore.activate = () => void idleTimer.current.activate();
    const stopListening = studyStore.listen();
    const onVisibility = () => {
      const shown = document.visibilityState === "visible";
      setVisible(shown);
      if (shown) void studyStore.refresh(); // another tab or device may have changed it meanwhile
    };
    const onOnline = () => {
      setOnline(true);
      void studyStore.refresh();
    };
    const onOffline = () => {
      setOnline(false);
      studyStore.set({ offline: true });
    };
    setVisible(document.visibilityState === "visible");
    setOnline(navigator.onLine);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    void beat(); // presence, and the session as it is
    const interval = window.setInterval(() => {
      // A reply being written is being read: the same rule as active time in PadhAI.
      if (isStreaming() && !idleTimer.current.isIdle()) idleTimer.current.reset();
      void beat();
    }, BEAT_EVERY_MS);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      stopListening();
      studyStore.flush = null;
      studyStore.acted = null;
      studyStore.activate = null;
    };
  }, [beat, isStreaming]);
}
