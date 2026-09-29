/**
 * Dictation with the browser's own speech recognition (Web Speech API). No audio reaches AI
 * Tutor: the browser's speech service turns speech into text, and only FINAL results are added
 * to the draft; the student still presses Send. Where the API is missing (Firefox) the mic is
 * not shown. The DOM library has no types for it, so the part used is declared here.
 */

type SpeechAlternative = { transcript: string };
type SpeechResult = { readonly isFinal: boolean; readonly length: number; readonly [index: number]: SpeechAlternative };
export type SpeechResultEvent = {
  resultIndex: number;
  results: { readonly length: number; readonly [index: number]: SpeechResult };
};
export type SpeechErrorEvent = { error: string };

export interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
export type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

/** The browser's recognizer, or null where there is none (then the mic is hidden). */
export function speechRecognitionCtor(scope: unknown): SpeechRecognitionConstructor | null {
  const found = scope as {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  } | null;
  return found?.SpeechRecognition ?? found?.webkitSpeechRecognition ?? null;
}

/** The final text of a result event; interim guesses are ignored. */
export function finalTranscript(event: SpeechResultEvent): string {
  let text = "";
  for (let index = event.resultIndex; index < event.results.length; index += 1) {
    const result = event.results[index];
    if (result?.isFinal) text += result[0]?.transcript ?? "";
  }
  return text.trim();
}

/** Dictated text goes after what is already typed, never over it. */
export function appendTranscript(draft: string, text: string): string {
  const spoken = text.trim();
  if (!spoken) return draft;
  if (!draft) return spoken;
  return /\s$/.test(draft) ? `${draft}${spoken}` : `${draft} ${spoken}`;
}

/** What to tell the student when recognition stops with an error; null when there is nothing to say. */
export function dictationErrorMessage(code: string): string | null {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access is blocked. Allow it for this site in your browser settings.";
    case "no-speech":
      return "Didn't catch that. Try again.";
    case "audio-capture":
      return "No microphone was found.";
    case "network":
      return "Dictation needs an internet connection.";
    case "aborted":
      return null;
    default:
      return "Dictation stopped. Try again.";
  }
}
