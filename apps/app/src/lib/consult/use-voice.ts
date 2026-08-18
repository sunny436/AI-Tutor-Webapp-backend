"use client";

/**
 * Microphone recording for the chat composer.
 *
 * WHY THIS RE-ENCODES TO WAV
 * MediaRecorder gives you webm/opus on Chrome and mp4/aac on Safari. The audio
 * chat API accepts wav and mp3 and neither of those. Rather than ship an ffmpeg
 * build or a server-side transcode step, the clip is decoded with the Web Audio
 * API and written back out as 16 kHz mono 16-bit WAV - about forty lines, no
 * dependency, and it makes the format identical on every browser.
 *
 * 16 kHz mono is not a compromise here: speech models downsample to it anyway,
 * and it makes the upload roughly six times smaller than 48 kHz stereo.
 */

import { useCallback, useRef, useState } from "react";

const TARGET_SAMPLE_RATE = 16000;

/** Write a PCM buffer out as a RIFF/WAVE file. */
function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++)
      view.setUint8(offset + i, text.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true); // PCM header size
  view.setUint16(20, 1, true); // format: uncompressed PCM
  view.setUint16(22, 1, true); // channels: mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);

  // Float -1..1 to signed 16-bit. Clamping matters: a value even slightly past
  // 1.0 wraps to a large negative number and becomes an audible click.
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i] ?? 0));
    view.setInt16(offset, clamped * 0x7fff, true);
    offset += 2;
  }
  return new Blob([view], { type: "audio/wav" });
}

/** Decode whatever the recorder produced and re-encode it as 16 kHz mono WAV. */
async function toWav(blob: Blob): Promise<Blob> {
  const bytes = await blob.arrayBuffer();
  const decoder = new AudioContext();
  try {
    const decoded = await decoder.decodeAudioData(bytes);
    // OfflineAudioContext does the resample and the stereo-to-mono mix for us,
    // correctly, which hand-rolled sample dropping would not.
    const frames = Math.ceil(decoded.duration * TARGET_SAMPLE_RATE);
    const offline = new OfflineAudioContext(1, frames, TARGET_SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0), TARGET_SAMPLE_RATE);
  } finally {
    void decoder.close();
  }
}

export type VoiceState = "idle" | "recording" | "processing";

export function useVoiceRecorder(maxSeconds = 60) {
  const [state, setState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);

  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const resolver = useRef<((wav: Blob | null) => void) | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    // Release the mic, or the browser keeps showing the recording indicator
    // and the tab holds the device open.
    for (const track of recorder.current?.stream.getTracks() ?? []) track.stop();
    recorder.current = null;
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (typeof navigator === "undefined" || !navigator.mediaDevices) {
      // getUserMedia needs a secure context. localhost counts, so this is really
      // only hit when testing over a LAN IP - worth naming, because otherwise it
      // looks like the button is broken.
      setError("Microphone needs HTTPS or localhost.");
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const name = (err as Error)?.name;
      setError(
        name === "NotAllowedError"
          ? "Microphone blocked. Allow it in your browser's site settings."
          : name === "NotFoundError"
            ? "No microphone found."
            : "Could not start recording.",
      );
      return;
    }

    // Let the browser pick its own container - we re-encode afterwards anyway,
    // so forcing a mimeType here would only fail on Safari for no gain.
    const media = new MediaRecorder(stream);
    chunks.current = [];
    media.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.current.push(event.data);
    };
    media.onstop = async () => {
      cleanup();
      const raw = new Blob(chunks.current, { type: media.mimeType });
      try {
        const wav = raw.size > 0 ? await toWav(raw) : null;
        resolver.current?.(wav);
      } catch {
        setError("Could not read that recording.");
        resolver.current?.(null);
      } finally {
        resolver.current = null;
        setState("idle");
        setSeconds(0);
      }
    };

    recorder.current = media;
    media.start();
    setState("recording");
    setSeconds(0);
    timer.current = setInterval(() => {
      setSeconds((s) => {
        // Auto-stop rather than record forever: it bounds the upload size and
        // the per-turn cost, and nobody means to leave the mic on.
        if (s + 1 >= maxSeconds) recorder.current?.stop();
        return s + 1;
      });
    }, 1000);
  }, [cleanup, maxSeconds]);

  /** Stop and resolve with the WAV clip (or null if there was nothing usable). */
  const stop = useCallback((): Promise<Blob | null> => {
    if (!recorder.current || recorder.current.state === "inactive") {
      return Promise.resolve(null);
    }
    setState("processing");
    return new Promise((resolve) => {
      resolver.current = resolve;
      recorder.current?.stop();
    });
  }, []);

  const cancel = useCallback(() => {
    resolver.current = null;
    if (recorder.current?.state !== "inactive") recorder.current?.stop();
    cleanup();
    setState("idle");
    setSeconds(0);
  }, [cleanup]);

  return { state, error, seconds, start, stop, cancel, setError };
}
