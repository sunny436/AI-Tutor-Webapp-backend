"use client";

import { cn } from "@v1/ui/utils";
import { Keyboard, Mic, MicOff, PhoneOff } from "lucide-react";
import { useEffect, useRef } from "react";

import "./voice.css";
import { unlockAudio } from "./audio-unlock";
import { TutorFace } from "./tutor-face";
import { useVoiceSession } from "./use-voice-session";
import type { VoiceState } from "./voice-session";

const LABELS: Record<VoiceState, string> = {
  idle: "Voice mode ended",
  starting: "Starting…",
  listening: "Listening…",
  transcribing: "Thinking…",
  thinking: "Thinking…",
  speaking: "Speaking · tap the tutor to interrupt",
  interrupted: "Listening…",
  muted: "Microphone off",
  error: "Voice mode stopped",
  ending: "Ending…",
};

function dot(state: VoiceState): string {
  if (state === "speaking") return "bg-success";
  if (state === "transcribing" || state === "thinking") return "bg-warning";
  if (state === "listening" || state === "interrupted" || state === "starting") return "bg-brand motion-safe:animate-pulse";
  return "bg-text-secondary";
}

const CONTROL =
  "focus-ring grid h-12 w-12 place-items-center rounded-full transition-colors hover:bg-surface-2 disabled:opacity-50";

/**
 * Voice mode over the chat it belongs to (chat-view.tsx): only the tutor's face, what it is doing in a word or
 * two, and three controls: back to the chat (to type), the microphone on or off, and end. Nothing said is
 * written here, neither the student's words nor the reply (owner's decision, 2026-10-26): the chat stays mounted
 * underneath, so its draft and its place are there to come back to, and everything said here is in it as
 * ordinary messages. Escape goes back to the chat.
 *
 * The state line is announced.
 */
export default function VoiceMode({ chatKey, onClose }: { chatKey: string; onClose: (focusComposer: boolean) => void }) {
  const voice = useVoiceSession(chatKey);
  const { session, state, muted } = voice;
  const glow = useRef<HTMLButtonElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  const began = useRef(false);
  if (state !== "idle") began.current = true;

  // The microphone's level grows the face's glow: one CSS variable, no re-render.
  useEffect(() => {
    session.onLevel = (level) => glow.current?.style.setProperty("--voice-level", Math.min(1, level * 8).toFixed(2));
    return () => {
      session.onLevel = null;
    };
  }, [session]);

  // Ended by itself (the page was hidden or left): back to the chat.
  useEffect(() => {
    if (began.current && state === "idle") onClose(false);
  }, [state, onClose]);

  useEffect(() => {
    back.current?.focus();
  }, []);

  const interruptible = state === "speaking" || state === "thinking";
  const close = (focusComposer: boolean) => {
    session.end();
    onClose(focusComposer);
  };
  const closing = useRef(close);
  closing.current = close;

  // Escape goes back to the chat wherever focus is, but not from another dialog over this one (a streak
  // celebration closes itself).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("[role='dialog']") && !target.closest("[data-voice-mode]")) return;
      event.preventDefault();
      closing.current(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      role="dialog"
      aria-label="Voice mode"
      data-voice-mode=""
      data-voice-state={state}
      className="absolute inset-0 z-20 flex flex-col items-center justify-between gap-4 bg-background px-5 pb-[max(1rem,env(safe-area-inset-bottom))] pt-6 motion-safe:animate-in motion-safe:fade-in-0 duration-base ease-enter"
    >
      <p
        role="status"
        aria-live="polite"
        className="elev-1 flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5 text-sm font-medium text-foreground"
      >
        <span aria-hidden className={cn("inline-block h-2 w-2 rounded-full", dot(state))} />
        {LABELS[state]}
      </p>

      <div className="flex min-h-0 w-full max-w-xl flex-1 flex-col items-center justify-center gap-6 text-center">
        <button
          ref={glow}
          type="button"
          onClick={interruptible ? () => session.interrupt() : undefined}
          aria-label={interruptible ? "Interrupt the tutor" : "The tutor"}
          aria-disabled={!interruptible || undefined}
          tabIndex={interruptible ? 0 : -1}
          className={cn("focus-ring rounded-[40%] p-8", !interruptible && "cursor-default")}
        >
          <TutorFace state={state} expression={voice.expression} />
        </button>

        <div className="min-h-[4.5rem] space-y-2">
          {voice.notice && (
            <p role="status" className="text-sm text-text-secondary">
              {voice.notice}
            </p>
          )}
          {state === "error" && voice.error && (
            <div role="alert" className="space-y-3">
              <p className="text-sm text-foreground">{voice.error}</p>
              <button
                type="button"
                onClick={() => {
                  unlockAudio(); // a click: the audio may start again
                  session.start();
                }}
                className="focus-ring rounded-full bg-brand px-4 py-2 text-sm font-semibold text-brand-foreground transition-colors hover:bg-brand-hover"
              >
                Try again
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="elev-1 flex items-center gap-2 rounded-full border border-border bg-card p-1.5">
        <button
          ref={back}
          type="button"
          onClick={() => close(true)}
          aria-label="Back to the chat"
          title="Back to the chat"
          className={cn(CONTROL, "text-text-secondary hover:text-foreground")}
        >
          <Keyboard aria-hidden className="h-5 w-5" />
        </button>
        <button
          type="button"
          onClick={() => session.setMuted(!muted)}
          aria-label="Microphone"
          aria-pressed={!muted}
          title={muted ? "Turn the microphone on" : "Turn the microphone off"}
          disabled={state === "error" || state === "ending"}
          className={cn(CONTROL, muted ? "bg-surface-2 text-foreground" : "text-text-secondary hover:text-foreground")}
        >
          {muted ? <MicOff aria-hidden className="h-5 w-5" /> : <Mic aria-hidden className="h-5 w-5" />}
        </button>
        <button
          type="button"
          onClick={() => close(false)}
          aria-label="End voice mode"
          title="End voice mode"
          className={cn(CONTROL, "bg-destructive/10 text-destructive hover:bg-destructive/15")}
        >
          <PhoneOff aria-hidden className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
