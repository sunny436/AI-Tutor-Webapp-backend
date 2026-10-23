"use client";

import { useSyncExternalStore } from "react";

import { ApiError, describeError } from "@/lib/api/errors";
import { type StudyTransition, changeStudyContext, getStudyState, startStudy, transitionStudy } from "@/lib/api/study";
import type { StudyContext, StudyState } from "@/lib/api/types";

/**
 * The study session as this tab knows it: the server's state (the only source of study numbers:
 * every second shown comes from it) plus this tab's own facts (idle, prompting, offline, an action
 * in flight). One store per page load, read by the header control, Study Activity and Settings.
 *
 * Other tabs and devices change the session too: the server's answer to each beat (every 30 s)
 * brings it here, other tabs of this browser say so at once (BroadcastChannel), and coming back
 * to the tab or online reloads it. A 409 from an action means another tab or device got there
 * first: the state is reloaded and shown as it is.
 */
export type StudySnapshot = {
  server: StudyState | null;
  loadError: unknown;
  idle: boolean;
  prompting: boolean;
  offline: boolean;
  pending: "start" | "context" | StudyTransition | null;
  actionError: string | null;
  /** The ended session whose notice this tab has dismissed. */
  dismissedEnded: string | null;
};

const CHANNEL = "padhai-study";
const DISMISSED_KEY = "padhai.study.dismissedEnded";

const INITIAL: StudySnapshot = {
  server: null,
  loadError: null,
  idle: false,
  prompting: false,
  offline: false,
  pending: null,
  actionError: null,
  dismissedEnded: null,
};

class StudyStore {
  private snapshot: StudySnapshot = INITIAL;
  private readonly listeners = new Set<() => void>();
  private id: string | null = null;
  private channel: BroadcastChannel | null = null;
  /** Set by the heartbeat: send an observation now (before pause, end or a context change, so
   * the server credits up to that moment), and learn what an action told the server. */
  flush: (() => Promise<void>) | null = null;
  acted: ((active: boolean) => void) | null = null;
  /** "I'm still studying": the reading prompt's answer (this tab's idle timer). */
  activate: (() => void) | null = null;

  /** This page load (never stored: a duplicated tab must not share it). */
  get clientId(): string {
    this.id ??= crypto.randomUUID();
    return this.id;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  get = (): StudySnapshot => this.snapshot;

  set(patch: Partial<StudySnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }

  apply(server: StudyState): void {
    // Never back to an older state: a beat sent before an action can be answered after it, and its
    // session (the segment before a resume, say) would make the next action a 409.
    const shown = this.snapshot.server;
    const older = shown !== null && Date.parse(server.serverTime) < Date.parse(shown.serverTime);
    this.set({ ...(older ? {} : { server }), loadError: null, offline: false });
  }

  async refresh(): Promise<void> {
    try {
      this.apply(await getStudyState());
    } catch (error) {
      if (!this.snapshot.server) this.set({ loadError: error });
    }
  }

  /** Other tabs of this browser: reload when one of them changed the session. */
  listen(): () => void {
    if (typeof BroadcastChannel === "undefined") return () => undefined;
    this.channel = new BroadcastChannel(CHANNEL);
    this.channel.onmessage = () => void this.refresh();
    try {
      this.set({ dismissedEnded: window.sessionStorage.getItem(DISMISSED_KEY) });
    } catch {
      // storage unavailable: the notice simply shows again
    }
    return () => {
      this.channel?.close();
      this.channel = null;
    };
  }

  dismissEnded(id: string): void {
    this.set({ dismissedEnded: id });
    try {
      window.sessionStorage.setItem(DISMISSED_KEY, id);
    } catch {
      // per-tab UI state only
    }
  }

  private async act(kind: NonNullable<StudySnapshot["pending"]>, call: () => Promise<StudyState>): Promise<void> {
    if (this.snapshot.pending) return; // one action at a time: no double submits
    this.set({ pending: kind, actionError: null });
    try {
      if (kind !== "start" && kind !== "resume") await this.flush?.();
      const state = await call();
      this.apply(state);
      this.acted?.(state.session?.status === "active" && kind !== "pause" && kind !== "end");
      this.channel?.postMessage("changed");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await this.refresh();
        this.set({ actionError: "Your study session was changed on another tab or device. This is how it is now." });
      } else {
        this.set({ actionError: describeError(error).message });
      }
    } finally {
      this.set({ pending: null });
    }
  }

  start(context: StudyContext): Promise<void> {
    return this.act("start", () => startStudy(this.clientId, context));
  }

  transition(action: StudyTransition): Promise<void> {
    const session = this.snapshot.server?.session;
    if (!session?.segment) return this.refresh();
    const { id, segment } = session;
    return this.act(action, () => transitionStudy(action, id, this.clientId, segment.id));
  }

  changeContext(context: StudyContext): Promise<void> {
    const session = this.snapshot.server?.session;
    if (!session?.segment) return this.refresh();
    const { id, segment } = session;
    return this.act("context", () => changeStudyContext(id, this.clientId, segment.id, context));
  }
}

export const studyStore = new StudyStore();

export function useStudy(): StudySnapshot {
  return useSyncExternalStore(studyStore.subscribe, studyStore.get, () => INITIAL);
}
