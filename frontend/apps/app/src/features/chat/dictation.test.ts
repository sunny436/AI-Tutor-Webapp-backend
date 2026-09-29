import { describe, expect, test } from "bun:test";

import {
  type SpeechResultEvent,
  appendTranscript,
  dictationErrorMessage,
  finalTranscript,
  speechRecognitionCtor,
} from "./dictation";

function event(resultIndex: number, results: { text: string; isFinal: boolean }[]): SpeechResultEvent {
  return {
    resultIndex,
    results: results.map(({ text, isFinal }) => Object.assign([{ transcript: text }], { isFinal })),
  } as unknown as SpeechResultEvent;
}

describe("dictation", () => {
  test("finds the recognizer, prefixed or not, and none where the browser has none (mic hidden)", () => {
    class Recognizer {}
    expect(speechRecognitionCtor({ webkitSpeechRecognition: Recognizer })).toBe(Recognizer as never);
    expect(speechRecognitionCtor({ SpeechRecognition: Recognizer })).toBe(Recognizer as never);
    expect(speechRecognitionCtor({})).toBeNull();
    expect(speechRecognitionCtor(undefined)).toBeNull();
  });

  test("only final results become text; interim guesses are ignored", () => {
    expect(finalTranscript(event(0, [{ text: "photo", isFinal: false }]))).toBe("");
    expect(finalTranscript(event(0, [{ text: " photosynthesis in plants ", isFinal: true }]))).toBe(
      "photosynthesis in plants",
    );
    // Earlier results (before resultIndex) were already handled.
    expect(
      finalTranscript(
        event(1, [
          { text: "old", isFinal: true },
          { text: "new words", isFinal: true },
        ]),
      ),
    ).toBe("new words");
  });

  test("dictated text is added after the draft, never over it", () => {
    expect(appendTranscript("", "hello")).toBe("hello");
    expect(appendTranscript("Explain", "osmosis")).toBe("Explain osmosis");
    expect(appendTranscript("Line one\n", "line two")).toBe("Line one\nline two");
    expect(appendTranscript("Keep this", "   ")).toBe("Keep this");
  });

  test("errors read as something to do; a deliberate stop says nothing", () => {
    expect(dictationErrorMessage("not-allowed")).toContain("Microphone access is blocked");
    expect(dictationErrorMessage("service-not-allowed")).toContain("Microphone access is blocked");
    expect(dictationErrorMessage("no-speech")).toContain("Didn't catch that");
    expect(dictationErrorMessage("audio-capture")).toContain("No microphone");
    expect(dictationErrorMessage("network")).toContain("internet connection");
    expect(dictationErrorMessage("aborted")).toBeNull();
    expect(dictationErrorMessage("something-new")).toContain("Try again");
  });
});
