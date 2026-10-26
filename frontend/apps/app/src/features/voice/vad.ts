/**
 * When the student is speaking, from the microphone's level and how much of it is in the voice band.
 *
 * Every FRAME_MS: the frame's loudness (RMS of the samples) and its speech-band ratio (power in 300-3400 Hz over
 * 80-8000 Hz: a fan's hum or a hiss is mostly outside it). A frame counts as speech when it is well above the
 * room's own level (calibrated over the first CALIBRATE_MS, then followed slowly while quiet) and mostly in the
 * band. Speech starts after ONSET_MS of it and ends after END_MS of quiet; while the tutor is speaking (or about
 * to) the bar is higher and the onset longer, so its own voice, if the browser's echo cancellation leaves any,
 * rarely counts. These values are starting points, measured in e2e/voice.e2e.ts; tap to interrupt always works.
 */

export const FRAME_MS = 30;
export const CALIBRATE_MS = 500;
export const ONSET_MS = { listen: 150, playback: 400 };
export const END_MS = 600; // the owner's choice (2026-10-26): a 0.6 s pause ends the question (was 0.8 s)
// The room's level is never taken as more than `max`: a student who speaks while it is being learnt still
// clears the bar (3 x 0.02) with ordinary speech.
const FLOOR = { min: 0.002, max: 0.02 };
const BAR = { listen: { times: 3, least: 0.012 }, playback: { times: 6, least: 0.03 } };
const MIN_BAND = 0.35;

export type VadMode = keyof typeof ONSET_MS;
export type Vad = { floor: number; calibrated: number; speech: number; quiet: number; speaking: boolean };

export const freshVad = (): Vad => ({ floor: 0, calibrated: 0, speech: 0, quiet: 0, speaking: false });

/** A new utterance, keeping what was learnt of the room. */
export const resetVad = (vad: Vad): Vad => ({ ...vad, speech: 0, quiet: 0, speaking: false });

export function rms(samples: Float32Array): number {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return samples.length ? Math.sqrt(sum / samples.length) : 0;
}

/** Of a spectrum in dB (AnalyserNode.getFloatFrequencyData), the share of power in the voice band. */
export function voiceBand(decibels: Float32Array, sampleRate: number): number {
  const hzPerBin = sampleRate / 2 / decibels.length;
  let band = 0;
  let total = 0;
  decibels.forEach((db, bin) => {
    const hz = bin * hzPerBin;
    if (hz < 80 || hz > 8000 || !Number.isFinite(db)) return;
    const power = 10 ** (db / 10);
    total += power;
    if (hz >= 300 && hz <= 3400) band += power;
  });
  return total > 0 ? band / total : 0;
}

/** One frame: the detector's next state, and "start" or "end" of speech when one happened. */
export function vadStep(vad: Vad, level: number, band: number, mode: VadMode): { vad: Vad; event: "start" | "end" | null } {
  if (vad.calibrated < CALIBRATE_MS) {
    const frames = vad.calibrated / FRAME_MS;
    const floor = (vad.floor * frames + level) / (frames + 1);
    return { vad: { ...vad, floor: clampFloor(floor), calibrated: vad.calibrated + FRAME_MS }, event: null };
  }
  const bar = Math.max(vad.floor * BAR[mode].times, BAR[mode].least);
  const speech = level > bar && band >= MIN_BAND;
  const next: Vad = { ...vad };
  if (speech) {
    next.speech += FRAME_MS;
    next.quiet = 0;
  } else {
    next.quiet += FRAME_MS;
    if (!vad.speaking) {
      next.speech = Math.max(0, next.speech - FRAME_MS); // a lone loud frame fades
      next.floor = clampFloor(vad.floor * 0.97 + level * 0.03); // follow the room while it is quiet
    }
  }
  if (!vad.speaking && next.speech >= ONSET_MS[mode]) return { vad: { ...next, speaking: true, quiet: 0 }, event: "start" };
  if (vad.speaking && next.quiet >= END_MS) return { vad: { ...next, speaking: false, speech: 0 }, event: "end" };
  return { vad: next, event: null };
}

function clampFloor(floor: number): number {
  return Math.min(FLOOR.max, Math.max(FLOOR.min, floor));
}

/** The browser's recorder format: the first one OllaLink was seen to accept (WebM/Opus, MP4/AAC), or none. */
export const RECORDER_TYPES = ["audio/webm;codecs=opus", "audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/webm"];

export function recorderType(isSupported: (type: string) => boolean): string | null {
  return RECORDER_TYPES.find((type) => isSupported(type)) ?? null;
}
