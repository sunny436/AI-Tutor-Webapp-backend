"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type SpeechRecognitionLike,
  dictationErrorMessage,
  finalTranscript,
  speechRecognitionCtor,
} from "./dictation";

export type DictationState = "idle" | "listening" | "stopping";

/**
 * One utterance per start (continuous off: predictable on phones too). Only the current session's
 * events count, so a result arriving after a stop, a send or a chat switch is dropped.
 */
export function useDictation(onText: (text: string) => void) {
  const [supported, setSupported] = useState(false); // known only after mount (no hydration mismatch)
  const [state, setState] = useState<DictationState>("idle");
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const session = useRef(0);
  const current = useRef<DictationState>("idle");
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  const move = useCallback((next: DictationState) => {
    current.current = next;
    setState(next);
  }, []);

  const abort = useCallback(() => {
    session.current += 1;
    recognition.current?.abort();
    recognition.current = null;
    move("idle");
  }, [move]);

  useEffect(() => {
    setSupported(speechRecognitionCtor(window) !== null);
    return () => {
      session.current += 1;
      recognition.current?.abort();
      recognition.current = null;
    };
  }, []);

  const start = useCallback(() => {
    const Recognition = speechRecognitionCtor(window);
    if (!Recognition || current.current !== "idle") return;
    const token = ++session.current;
    const next = new Recognition();
    next.lang = navigator.language || "en-IN";
    next.interimResults = false;
    next.continuous = false;
    next.maxAlternatives = 1;
    next.onresult = (event) => {
      if (token !== session.current) return;
      const text = finalTranscript(event);
      if (text) onTextRef.current(text);
    };
    next.onerror = (event) => {
      if (token !== session.current) return;
      const message = dictationErrorMessage(event.error);
      if (message) setError(message);
    };
    next.onend = () => {
      if (token !== session.current) return;
      recognition.current = null;
      move("idle");
    };
    setError(null);
    try {
      next.start();
      recognition.current = next;
      move("listening");
    } catch {
      recognition.current = null;
      move("idle");
      setError("Dictation couldn't start. Try again.");
    }
  }, [move]);

  const toggle = useCallback(() => {
    if (current.current === "idle") start();
    else if (current.current === "listening" && recognition.current) {
      move("stopping");
      recognition.current.stop(); // the final words still arrive, then onend
    }
  }, [start, move]);

  return { supported, state, error, clearError: () => setError(null), toggle, abort };
}
