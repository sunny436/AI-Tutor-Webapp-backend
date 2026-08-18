"use client";

/**
 * Read one answer aloud — free, using the browser's own speech engine.
 *
 * WHY NOT A MODEL
 * Of the 400 models on OpenRouter exactly four emit audio: two are paid, and two
 * (google/lyria-*) generate music rather than speech. So there is no free
 * text-to-speech model to call. But every modern browser already ships one -
 * `window.speechSynthesis`, the Web Speech API - and it costs nothing, needs no
 * key, works offline, and starts instantly instead of after a round trip.
 *
 * A paid model still sounds better. If `TTS_MODEL` is set in the backend .env,
 * `POST /speak` answers and that is used instead; otherwise this falls back to
 * the browser. Free by default, better if you pay - decided at runtime by
 * whether /speak returns 503.
 *
 * On demand only, never on arrival: a plan runs past 1,500 characters and
 * autoplaying that would be obnoxious.
 */

import { Loader2, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AI_BACKEND_URL } from "@/lib/consult/client";

const DEVANAGARI = /[ऀ-ॿ]/;

/** Strip markdown so the engine does not read "asterisk asterisk" aloud. */
function forSpeech(text: string): string {
  return text
    .replace(/\*\*/g, "")
    .replace(/^#+\s*/gm, "")
    .replace(/^[-*]\s+/gm, "")
    .replace(/`/g, "")
    .replace(/\n{2,}/g, ". ")
    .trim();
}

/**
 * Pick a voice for the text.
 *
 * Hinglish is the awkward case: it is Hindi written in Latin letters, so a
 * pure-English voice mangles the Hindi words and a Hindi voice cannot read the
 * Latin ones. `en-IN` is the best compromise - an Indian English voice handles
 * "khana", "subah" and "dosha" far more naturally than en-US does.
 */
function pickVoice(text: string, voices: SpeechSynthesisVoice[]) {
  const wantHindi = DEVANAGARI.test(text);
  const preferred = wantHindi ? ["hi-IN", "hi"] : ["en-IN", "en-GB", "en-US", "en"];
  for (const tag of preferred) {
    const found = voices.find((v) => v.lang.toLowerCase().startsWith(tag.toLowerCase()));
    if (found) return found;
  }
  return voices[0];
}

export function SpeakButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const cached = useRef<string | null>(null);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const load = () => setVoices(window.speechSynthesis.getVoices());
    load();
    // Chrome populates the voice list asynchronously, so the first getVoices()
    // usually returns an empty array. Without this listener the very first
    // press gets the default voice regardless of language.
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);

  // Stop any speech and release the blob URL on unmount, or navigating away
  // mid-sentence leaves the browser talking to an empty room.
  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel();
      audio.current?.pause();
      if (cached.current) URL.revokeObjectURL(cached.current);
    };
  }, []);

  const speakInBrowser = useCallback(
    (body: string) => {
      const synth = window.speechSynthesis;
      if (!synth) {
        toast.error("This browser cannot read text aloud.");
        setState("idle");
        return;
      }
      synth.cancel();
      const utterance = new SpeechSynthesisUtterance(forSpeech(body));
      const voice = pickVoice(body, voices);
      if (voice) {
        utterance.voice = voice;
        utterance.lang = voice.lang;
      }
      // Slightly under normal. Wellness advice is instructions, and the default
      // rate reads them faster than anyone can follow.
      utterance.rate = 0.95;
      utterance.onend = () => setState("idle");
      utterance.onerror = () => setState("idle");
      synth.speak(utterance);
      setState("playing");
    },
    [voices],
  );

  const playFile = useCallback(async (url: string) => {
    audio.current ??= new Audio();
    audio.current.src = url;
    audio.current.onended = () => setState("idle");
    audio.current.onerror = () => setState("idle");
    try {
      await audio.current.play();
      setState("playing");
    } catch {
      setState("idle");
    }
  }, []);

  const toggle = async () => {
    if (state === "playing") {
      window.speechSynthesis?.cancel();
      audio.current?.pause();
      setState("idle");
      return;
    }

    if (cached.current) {
      void playFile(cached.current);
      return;
    }

    setState("loading");
    try {
      const response = await fetch(`${AI_BACKEND_URL}/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (response.status === 503) {
        // No paid voice model configured, which is the default. Use the
        // browser's engine - free, and the reason this button still works.
        speakInBrowser(text);
        return;
      }
      if (!response.ok) throw new Error(String(response.status));

      const { audio: b64, format } = (await response.json()) as {
        audio: string;
        format: string;
      };
      if (!b64) throw new Error("empty");

      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(
        new Blob([bytes], { type: `audio/${format || "wav"}` }),
      );
      cached.current = url;
      void playFile(url);
    } catch {
      // Backend unreachable, or the paid call failed. Speaking locally is
      // strictly better than telling the user it did not work.
      speakInBrowser(text);
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={state === "loading" || !text.trim()}
      title={state === "playing" ? "Stop" : "Read this out loud"}
      className="focus-ring mt-1 flex items-center gap-1.5 rounded-md px-1.5 py-1 text-2xs font-medium text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
    >
      {state === "loading" ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : state === "playing" ? (
        <VolumeX className="h-3 w-3" />
      ) : (
        <Volume2 className="h-3 w-3" />
      )}
      {state === "playing" ? "Stop" : "Listen"}
    </button>
  );
}
