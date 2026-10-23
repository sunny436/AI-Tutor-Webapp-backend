import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { Page } from "@playwright/test";

/**
 * Voice mode's e2e microphone: a WAV Chromium plays as the microphone (`--use-file-for-fake-audio-capture`), looped:
 * quiet, a stretch of speech-like sound (harmonics of 220 Hz in the voice band, four "syllables" a second), quiet.
 * Made here, before the browser starts, so no audio is committed. The API's fake speech hears any recording as
 * "What is photosynthesis?" (app/voice/provider.py FakeVoice).
 */
export function fakeMicrophone(name: string, quietBefore: number, speech: number, quietAfter: number): string {
  const rate = 16_000;
  const frames = Math.round((quietBefore + speech + quietAfter) * rate);
  const data = Buffer.alloc(frames * 2);
  for (let n = 0; n < frames; n += 1) {
    const t = n / rate - quietBefore;
    let sample = 0;
    if (t >= 0 && t < speech) {
      for (let harmonic = 2; harmonic <= 12; harmonic += 1) sample += Math.sin(2 * Math.PI * 220 * harmonic * t) / harmonic;
      sample *= 0.3 * (0.55 + 0.45 * Math.sin(2 * Math.PI * 4 * t));
    }
    data.writeInt16LE(Math.max(-32_767, Math.min(32_767, Math.round(sample * 32_767))), n * 2);
  }
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write("WAVEfmt ", 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(data.length, 40);
  const path = join(tmpdir(), `padhai-voice-${name}.wav`);
  writeFileSync(path, Buffer.concat([header, data]));
  return path;
}

export function microphoneArgs(path: string): string[] {
  return [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    `--use-file-for-fake-audio-capture=${path}`,
    "--autoplay-policy=no-user-gesture-required",
  ];
}

/** Keeps every stream the page opens, so a test can see that none is left listening. */
export const KEEP_STREAMS = () => {
  const media = navigator.mediaDevices;
  if (!media?.getUserMedia) return;
  const original = media.getUserMedia.bind(media);
  const kept: MediaStream[] = [];
  (window as unknown as { __streams: MediaStream[] }).__streams = kept;
  media.getUserMedia = async (constraints) => {
    const stream = await original(constraints);
    kept.push(stream);
    return stream;
  };
};

export const liveTracks = (page: Page) =>
  page.evaluate(
    () =>
      ((window as unknown as { __streams?: MediaStream[] }).__streams ?? [])
        .flatMap((stream) => stream.getTracks())
        .filter((track) => track.readyState === "live").length,
  );

export type VoiceTurn = {
  speechEnd?: number;
  transcript?: number;
  firstToken?: number;
  firstSpeechRequest?: number;
  firstAudio?: number;
  replyDone?: number;
  interrupted?: number;
  silent?: number;
};

export const voiceTurns = (page: Page) =>
  page.evaluate(() => (window as unknown as { __padhaiVoice?: { turns: VoiceTurn[] } }).__padhaiVoice?.turns ?? []);
