import { describe, expect, test } from "bun:test";

import { CALIBRATE_MS, END_MS, FRAME_MS, ONSET_MS, type Vad, freshVad, recorderType, rms, vadStep, voiceBand } from "./vad";
import { TRANSITIONS, type VoiceState, canMove } from "./voice-session";

/** Run frames of `level` (voice-band ratio `band`) through the detector; the events, with when they came. */
function run(vad: Vad, frames: [level: number, count: number][], band = 0.9, mode: "listen" | "playback" = "listen") {
  const events: [string, number][] = [];
  let time = 0;
  let state = vad;
  for (const [level, count] of frames) {
    for (let i = 0; i < count; i += 1) {
      const step = vadStep(state, level, band, mode);
      state = step.vad;
      time += FRAME_MS;
      if (step.event) events.push([step.event, time]);
    }
  }
  return { events, vad: state };
}

const calibrated = (level = 0.003) => run(freshVad(), [[level, CALIBRATE_MS / FRAME_MS]]).vad;
/** The detector counts whole frames: a duration is reached on the frame that passes it. */
const frames = (ms: number) => Math.ceil(ms / FRAME_MS) * FRAME_MS;

describe("when the student is speaking (vad.ts)", () => {
  test("loudness and the voice band are measured from the microphone's data", () => {
    expect(rms(new Float32Array([0.5, -0.5, 0.5, -0.5]))).toBeCloseTo(0.5);
    const spectrum = new Float32Array(512).fill(-120);
    spectrum.fill(-20, 20, 150); // 940-7000 Hz at 48 kHz: mostly voice band
    expect(voiceBand(spectrum, 48_000)).toBeGreaterThan(0.35);
    const hum = new Float32Array(512).fill(-120);
    hum.fill(-20, 2, 6); // under 300 Hz: a fan's hum
    expect(voiceBand(hum, 48_000)).toBeLessThan(0.35);
  });

  test("the room's level is learnt first; then speech starts after its onset and ends after a pause", () => {
    const quietRoom = calibrated();
    const { events } = run(quietRoom, [
      [0.1, 20], // 600 ms of speech
      [0.003, 40], // then 1.2 s of quiet
    ]);
    expect(events.map(([event]) => event)).toEqual(["start", "end"]);
    expect(events[0]?.[1]).toBe(frames(ONSET_MS.listen));
    expect((events[1]?.[1] ?? 0) - 600).toBe(frames(END_MS));
  });

  test("a lone loud frame (a click, a cough) is not speech; nor is loud sound outside the voice band", () => {
    expect(run(calibrated(), [[0.2, 2], [0.003, 30]]).events).toEqual([]);
    expect(run(calibrated(), [[0.2, 30]], 0.1).events).toEqual([]);
  });

  test("while the tutor speaks the bar is higher and the onset longer (its own voice rarely counts)", () => {
    const room = calibrated();
    expect(run(room, [[0.02, 30]], 0.9, "playback").events).toEqual([]); // fine for listening, not over the tutor
    const loud = run(room, [[0.12, 30]], 0.9, "playback").events;
    expect(loud[0]).toEqual(["start", frames(ONSET_MS.playback)]);
  });

  test("speaking during the calibration does not make the bar unreachable", () => {
    const talkedOver = calibrated(0.2); // the student spoke while the room was being learnt
    expect(run(talkedOver, [[0.003, 10], [0.1, 20]]).events[0]?.[0]).toBe("start");
  });

  test("the recorder format: the first the provider was seen to accept, or none", () => {
    expect(recorderType(() => true)).toBe("audio/webm;codecs=opus");
    expect(recorderType((type) => type.startsWith("audio/mp4"))).toBe("audio/mp4;codecs=mp4a.40.2");
    expect(recorderType((type) => type === "audio/ogg;codecs=opus")).toBeNull(); // not verified: refused
  });
});

describe("the voice session's states (voice-session.ts TRANSITIONS)", () => {
  const states = Object.keys(TRANSITIONS) as VoiceState[];

  test("every state can end, and ending only ever leads back to idle", () => {
    for (const state of states) {
      if (state !== "idle" && state !== "ending") expect(canMove(state, "ending"), state).toBe(true);
    }
    expect(TRANSITIONS.ending).toEqual(["idle"]);
    expect(TRANSITIONS.idle).toEqual(["starting"]);
  });

  test("a turn goes listening → transcribing → thinking → speaking → listening, and may be interrupted", () => {
    const turn: VoiceState[] = ["idle", "starting", "listening", "transcribing", "thinking", "speaking", "listening"];
    for (let i = 1; i < turn.length; i += 1) expect(canMove(turn[i - 1] as VoiceState, turn[i] as VoiceState)).toBe(true);
    for (const busy of ["thinking", "speaking"] as VoiceState[]) expect(canMove(busy, "interrupted")).toBe(true);
    expect(canMove("interrupted", "transcribing")).toBe(true);
  });

  test("nothing skips ahead: no speaking before thinking, no turn from idle or after an error without a start", () => {
    expect(canMove("listening", "speaking")).toBe(false);
    expect(canMove("idle", "listening")).toBe(false);
    expect(canMove("error", "listening")).toBe(false);
    expect(canMove("error", "starting")).toBe(true); // Try again
    expect(canMove("muted", "transcribing")).toBe(false); // muted hears nothing
    for (const state of states) for (const next of TRANSITIONS[state]) expect(states).toContain(next);
  });
});
