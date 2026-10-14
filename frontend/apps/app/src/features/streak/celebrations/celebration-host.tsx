"use client";

import { Button } from "@v1/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@v1/ui/dialog";
import { type ComponentType, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { useUser } from "@/components/user-context";
import { CELEBRATE_EVENT } from "@/lib/activity";
import { useStreak } from "../streak-store";
import { GoalExtended } from "./goal-extended";
import { type Celebration, EMPTY_QUEUE, type QueueState, finish, lostFor, offer } from "./queue";
import { StreakLost } from "./streak-lost";
import { StreakMilestone } from "./streak-milestone";
import { StreakStarted } from "./streak-started";

/**
 * The streak celebrations, one at a time (queue.ts), wherever the student chats (AppShell): the
 * animation in the centre, over the page blurred behind it.
 *
 *   Started    the server's `done.learning` "started": day 1 of a streak
 *   Extended   "extended": the day's goal done, the streak one longer
 *   Milestone  "milestone": every 7th day (7, 14, 21, …)
 *   Lost       the streak store: 0 after a whole missed India day (never while today is pending)
 *
 * - Never over an answer still appearing: a celebration waits until no reply is streaming and the
 *   chat has been still for a moment (the last words have arrived, maths and diagrams are drawn).
 * - The card and its drawing appear in the same frame: the drawings are part of this code (a few
 *   KB), never fetched when the card opens.
 * - A dialog: focus moves to its button and comes back where the student was; Esc, ✕, a click
 *   outside or the button close it. Started, Extended and Lost close by themselves after a few
 *   seconds, so learning goes on; a milestone waits for the student. The drawing is decorative:
 *   the text says what happened.
 */

const DRAWINGS: Record<Celebration["kind"], ComponentType<{ className?: string }>> = {
  started: StreakStarted,
  extended: GoalExtended,
  milestone: StreakMilestone,
  lost: StreakLost,
};

/** How long a celebration stays by itself; null: until the student closes it. */
const STAYS_MS: Record<Celebration["kind"], number | null> = {
  started: 5000,
  extended: 5000,
  milestone: null,
  lost: 7000,
};
const LOST_SEEN = "padhai.streak-lost.";
/** The chat still this long (no reply streaming, nothing changing) before a celebration shows. */
const SETTLE_MS = 700;
/** Never wait longer than this (a reply streaming in another tab keeps one busy): never lost. */
const SETTLE_MAX_MS = 15_000;

/** Resolves once the chat has settled (see SETTLE_MS); `cancel` stops waiting. */
function whenChatSettled(): { settled: Promise<void>; cancel: () => void } {
  const chat = document.getElementById("main") ?? document.body;
  const busy = () => chat.querySelector("article[aria-label='Assistant'][aria-busy='true']") !== null;
  let quiet: number | undefined;
  let limit: number | undefined;
  let observer: MutationObserver | undefined;
  const cancel = () => {
    observer?.disconnect();
    window.clearTimeout(quiet);
    window.clearTimeout(limit);
  };
  const settled = new Promise<void>((resolve) => {
    const done = () => {
      cancel();
      resolve();
    };
    const arm = () => {
      window.clearTimeout(quiet);
      quiet = window.setTimeout(() => (busy() ? arm() : done()), SETTLE_MS);
    };
    observer = new MutationObserver(arm);
    observer.observe(chat, { subtree: true, childList: true, characterData: true });
    limit = window.setTimeout(done, SETTLE_MAX_MS);
    arm();
  });
  return { settled, cancel };
}

// The queue lives as long as the page, so a route change or a remount never replays a celebration.
let queue: QueueState = EMPTY_QUEUE;
const listeners = new Set<() => void>();

function update(next: QueueState): void {
  if (next === queue) return;
  queue = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const showing = () => queue.items[0] ?? null;

/** A lost streak is told once per account in this browser (the day it ended is remembered). */
function lostSeen(userId: string, lastDay: string): boolean {
  try {
    return window.localStorage.getItem(LOST_SEEN + userId) === lastDay;
  } catch {
    return false;
  }
}

function rememberLost(userId: string, lastDay: string): void {
  try {
    window.localStorage.setItem(LOST_SEEN + userId, lastDay);
  } catch {
    // storage unavailable: once per page instead (the queue remembers the key)
  }
}

export function CelebrationHost() {
  const { user } = useUser();
  const { status, data } = useStreak();
  const shown = useSyncExternalStore(subscribe, showing, () => null);

  useEffect(() => {
    const onCelebrate = (event: Event) => {
      const item = (event as CustomEvent<Celebration | undefined>).detail;
      if (item) update(offer(queue, item));
    };
    window.addEventListener(CELEBRATE_EVENT, onCelebrate);
    return () => window.removeEventListener(CELEBRATE_EVENT, onCelebrate);
  }, []);

  useEffect(() => {
    if (status !== "ready" || !data?.lastLearningDate) return;
    const lost = lostFor(user.id, data);
    if (!lost || lostSeen(user.id, data.lastLearningDate)) return;
    rememberLost(user.id, data.lastLearningDate);
    update(offer(queue, lost));
  }, [status, data, user.id]);

  // Leaving these pages ends the celebration on screen; it is not shown again on return.
  useEffect(
    () => () => {
      const first = queue.items[0];
      if (first) update(finish(queue, first.key));
    },
    [],
  );

  const key = shown?.key;
  const close = useCallback(() => {
    if (key) update(finish(queue, key));
  }, [key]);

  // Shown only once the chat has settled: never over an answer still appearing.
  const [settledFor, setSettledFor] = useState<string | null>(null);
  useEffect(() => {
    if (!key) return;
    const { settled, cancel } = whenChatSettled();
    void settled.then(() => setSettledFor(key));
    return cancel;
  }, [key]);

  return shown && settledFor === shown.key ? <CelebrationDialog key={shown.key} item={shown} onClose={close} /> : null;
}

function words(item: Celebration): { title: string; body: string; action: string } {
  switch (item.kind) {
    case "started":
      return { title: "Your streak has started!", body: "Day 1. Ask a question tomorrow to keep it going.", action: "Continue" };
    case "extended":
      return { title: "Daily goal complete!", body: "Come back tomorrow to keep your flame burning.", action: "Continue" };
    case "milestone":
      return {
        title: `${item.streak}-day streak!`,
        body: `${item.streak === 7 ? "A whole week" : `${item.streak / 7} weeks`} of learning in a row. Keep it going!`,
        action: "Keep learning",
      };
    case "lost":
      return {
        title: "A fresh start",
        body: `Your ${item.previous}-day streak has reset. Ask a question today to begin a new one.`,
        action: "Start learning",
      };
  }
}

function CelebrationDialog({ item, onClose }: { item: Celebration; onClose: () => void }) {
  const Drawing = DRAWINGS[item.kind];
  const action = useRef<HTMLButtonElement>(null);
  const { title, body, action: label } = words(item);
  const stays = STAYS_MS[item.kind];

  useEffect(() => {
    if (stays === null) return;
    const timer = window.setTimeout(onClose, stays);
    return () => window.clearTimeout(timer);
  }, [stays, onClose]);

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        data-celebration={`${item.kind}-dialog`}
        overlayClassName="bg-overlay/40 backdrop-blur-md"
        className="max-w-sm justify-items-center gap-3 rounded-3xl px-6 pb-6 pt-8 text-center"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          action.current?.focus();
        }}
      >
        <span aria-hidden className="block h-44 w-44">
          <Drawing className="h-44 w-44" />
        </span>
        {item.kind === "extended" && <StreakCount streak={item.streak} />}
        <DialogTitle className="text-center text-xl">{title}</DialogTitle>
        <DialogDescription className="text-center">{body}</DialogDescription>
        <Button ref={action} onClick={onClose} className="mt-1 min-w-36">
          {label}
        </Button>
      </DialogContent>
    </Dialog>
  );
}

/** The streak one longer: the number moves on as the flame lights. */
function StreakCount({ streak }: { streak: number }) {
  const [count, setCount] = useState(streak - 1);
  useEffect(() => {
    const rise = window.setTimeout(() => setCount(streak), 700);
    return () => window.clearTimeout(rise);
  }, [streak]);
  return (
    <p className="text-sm font-medium text-text-secondary">
      <span key={count} className="inline-block animate-rise-in text-2xl font-bold tabular-nums text-foreground">
        {count}
      </span>{" "}
      day streak
      <span className="sr-only">: your learning streak is now {streak} days</span>
    </p>
  );
}
