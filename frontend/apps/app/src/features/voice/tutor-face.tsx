import type { VoiceState } from "./voice-session";

/** What the face is doing (listening, thinking, speaking), apart from its manner (`expression`). */
export function faceState(state: VoiceState): "listening" | "thinking" | "speaking" | "resting" {
  if (state === "speaking") return "speaking";
  if (state === "transcribing" || state === "thinking") return "thinking";
  if (state === "listening" || state === "interrupted" || state === "starting") return "listening";
  return "resting";
}

/**
 * The tutor's face in voice mode (voice.css): a calm, rounded face with two hands. What it is doing shows in
 * its colour and movement; its manner (explaining, encouraging…) in its eyes, mouth and hands. Decorative: the
 * voice view says the state in words, so assistive technology never reads the face.
 */
export function TutorFace({ state, expression }: { state: VoiceState; expression: string }) {
  return (
    <span className="tutor" data-face={faceState(state)} data-expression={expression} aria-hidden>
      <span className="tutor-ring" />
      <span className="tutor-hand tutor-hand-left" />
      <span className="tutor-hand tutor-hand-right" />
      <span className="tutor-head">
        <span className="tutor-eyes">
          <span className="tutor-eye" />
          <span className="tutor-eye" />
        </span>
        <span className="tutor-mouth" />
      </span>
    </span>
  );
}
