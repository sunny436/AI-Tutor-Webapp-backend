/**
 * One voice conversation in one chat. The microphone is listened to; each thing the student says is recorded,
 * transcribed (OllaLink, through the API) and sent as their message in this chat, exactly like a typed one
 * (mode "voice"); the reply is read aloud while it is still being written (speech-text.ts, scheduler.ts). The
 * student can interrupt by speaking or with a tap, mute the microphone, go back to the chat or end.
 *
 * STATES (TRANSITIONS, tested): idle → starting → listening → transcribing → thinking → speaking → listening …;
 * also interrupted, muted, error and ending. Every asynchronous result carries its session and turn and is
 * dropped unless both are still current: a transcript, a reply or a sentence from an earlier turn never lands
 * in a newer one. Ending releases everything: the microphone, the recorder, audio, timers, listeners, requests.
 * The reply being written when voice mode ends still finishes in the chat; only its speech stops.
 *
 * Nothing is kept: the recording goes to the API once and is dropped; timings stay in this page (for QA).
 */

import { ApiError } from "@/lib/api/errors";
import type { SpeechFormat, SpeechRequest, StreamSpeech, VoiceAvailability, VoiceTranscript } from "@/lib/api/types";
import type { ChatStore } from "@/features/chat/chat-store";
import { type AudioOut, type Playable, SpeechScheduler } from "./scheduler";
import { SpeechChunker, type SpeechChunk } from "./speech-text";
import { END_MS, FRAME_MS, type Vad, freshVad, recorderType, resetVad, rms, vadStep, voiceBand } from "./vad";

export type VoiceState =
  | "idle"
  | "starting"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "muted"
  | "error"
  | "ending";

/** Where each state may go; anything else is a bug (refused and reported in development). */
export const TRANSITIONS: Record<VoiceState, readonly VoiceState[]> = {
  idle: ["starting"],
  starting: ["listening", "muted", "error", "ending"],
  listening: ["transcribing", "muted", "error", "ending"],
  transcribing: ["thinking", "listening", "muted", "interrupted", "error", "ending"],
  thinking: ["speaking", "listening", "muted", "interrupted", "error", "ending"],
  speaking: ["listening", "muted", "interrupted", "error", "ending"],
  interrupted: ["transcribing", "listening", "muted", "error", "ending"],
  muted: ["listening", "ending", "error"],
  error: ["starting", "ending"],
  ending: ["idle"],
};

export function canMove(from: VoiceState, to: VoiceState): boolean {
  return TRANSITIONS[from].includes(to);
}

export const EXPRESSIONS = new Set(["neutral", "happy", "explaining", "focused", "thinking", "encouraging"]);
/** The longest utterance, and the most of it to record (VOICE_UPLOAD's 1 MiB, with room for the container). */
export const MAX_UTTERANCE_MS = 60_000;
const MAX_RECORDING_BYTES = 960 * 1024;
/** Without speech, a recording is begun again this often, so it never carries a long silence. */
const IDLE_RECORDING_MS = 8_000;
const STREAM_END_WAIT_MS = 10_000;
/**
 * The pre-recorded acknowledgements (public/voice/ack-<n>.<ext>, the tutor's own voice), said in turn, and the
 * formats they come in, smallest first: the first one this browser decodes is the one its speech is asked in.
 */
const ACKS = 4;
const FORMATS: readonly (readonly [SpeechFormat, string])[] = [
  ["opus", "ogg"],
  ["aac", "aac"],
  ["mp3", "mp3"],
];

export type VoiceSnapshot = Readonly<{
  state: VoiceState;
  muted: boolean;
  expression: string;
  notice: string | null; // a recoverable problem, said plainly
  error: string | null; // why the session stopped
}>;

export type TurnTimings = {
  speechEnd?: number;
  ack?: number;
  transcript?: number;
  firstToken?: number;
  firstSpeechRequest?: number;
  firstAudio?: number;
  replyDone?: number;
  interrupted?: number;
  silent?: number;
};

export type VoiceDeps = {
  transcribe: (audio: Blob, seconds: number, signal?: AbortSignal) => Promise<VoiceTranscript>;
  synthesize: (request: SpeechRequest, signal?: AbortSignal) => Promise<ArrayBuffer>;
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  audio: () => AudioContext;
  /** What the API offers this student (the acknowledgement); none: no acknowledgement. */
  config?: () => Promise<VoiceAvailability>;
  /** A clip's bytes (public/voice); fetch by default. */
  fetchAudio?: (url: string) => Promise<ArrayBuffer>;
  now?: () => number;
};

type Store = Pick<ChatStore, "send" | "stop" | "getEntry" | "subscribe" | "getMessage" | "subscribeMessage">;

const MESSAGES = {
  denied: "Microphone access is blocked. Allow it for this site in your browser settings, then try again.",
  noMic: "No microphone was found.",
  lost: "The microphone stopped. Check it is connected, then try again.",
  format: "This browser can't record in a format voice mode supports. Try Chrome, Edge or Safari.",
  notHeard: "Didn't catch that. Please say it again.",
  incomplete: "Couldn't read the rest aloud; it's in the chat.",
  failed: "Something went wrong. Your chat is safe; try again.",
};

/** Web Audio; nothing of a reply starts before `notBefore()` (the acknowledgement playing). */
function webAudio(context: AudioContext, notBefore: () => number): AudioOut {
  return {
    async decode(bytes) {
      const buffer = await context.decodeAudioData(bytes);
      return Object.assign({ duration: buffer.duration, bytes: buffer.length * buffer.numberOfChannels * 4 }, { buffer });
    },
    play(audio: Playable, at: number) {
      const source = context.createBufferSource();
      source.buffer = (audio as Playable & { buffer: AudioBuffer }).buffer;
      source.connect(context.destination);
      let done: () => void = () => {};
      const ended = new Promise<void>((resolve) => {
        done = resolve;
      });
      source.onended = () => done();
      source.start(at);
      return {
        stop() {
          try {
            source.stop();
          } catch {
            // never started: nothing to stop
          }
          source.disconnect();
          done();
        },
        ended,
      };
    },
    now: () => Math.max(context.currentTime, notBefore()),
  };
}

/** Timings of the latest turns, in this page only (the QA spec reads them; nothing is sent anywhere). */
function record(timings: TurnTimings): void {
  const store = globalThis as { __padhaiVoice?: { turns: TurnTimings[] } };
  store.__padhaiVoice ??= { turns: [] };
  store.__padhaiVoice.turns.push(timings);
  if (store.__padhaiVoice.turns.length > 50) store.__padhaiVoice.turns.shift();
}

export class VoiceSession {
  private snapshot: VoiceSnapshot = {
    state: "idle",
    muted: false,
    expression: "neutral",
    notice: null,
    error: null,
  };
  private readonly listeners = new Set<() => void>();
  private readonly now: () => number;
  private session = 0;
  private turn = 0;
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private samples = new Float32Array(1024);
  private spectrum = new Float32Array(512);
  private vad: Vad = freshVad();
  private recorder: MediaRecorder | null = null;
  private recorded: Blob[] = [];
  private recordedBytes = 0;
  private recordingSince = 0;
  private speechSince = 0;
  private requests = new AbortController();
  private scheduler: SpeechScheduler | null = null;
  private chunker: SpeechChunker | null = null;
  private waiting: SpeechChunk[] = [];
  private reply: string | null = null;
  private finished = false;
  private spoke = false;
  private timings: TurnTimings = {};
  private unwatch: (() => void)[] = [];
  private format: SpeechFormat = "mp3"; // until a smaller one is seen to decode (prepareSpeech)
  private acks: Clip[] = [];
  private ackCount = 0;
  private ackEnd = 0; // on the audio clock: when the acknowledgement playing ends
  private quietUntil = 0; // on this.now(): the detector rests until then (the acknowledgement)
  private serverSpeech = false; // the server speaks a reply's first words (GET /v1/voice serverSpeech)
  private planWaiting = false; // this reply's first words: waiting for the server to say which
  private premade = new Map<string, Promise<ArrayBuffer>>(); // words the server is speaking: their audio
  private firstWords: { text: string; resolve: (audio: Promise<ArrayBuffer>) => void } | null = null;
  /** The level of the microphone, for the face (set by the view, called at most every FRAME_MS). */
  onLevel: ((level: number) => void) | null = null;

  constructor(
    private readonly chat: Store,
    private readonly chatKey: string,
    private readonly deps: VoiceDeps,
  ) {
    this.now = deps.now ?? (() => performance.now());
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): VoiceSnapshot => this.snapshot;

  private set(change: Partial<VoiceSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...change };
    for (const listener of this.listeners) listener();
  }

  private move(to: VoiceState): boolean {
    const from = this.snapshot.state;
    if (from === to) return true;
    if (!canMove(from, to)) {
      if (process.env.NODE_ENV !== "production") console.warn(`voice: ${from} → ${to} refused`);
      return false;
    }
    this.set({ state: to });
    return true;
  }

  // ------------------------------------------------------------------ the session
  start = (): void => {
    const state = this.snapshot.state;
    if (state !== "idle" && state !== "error") return;
    this.move("starting");
    this.set({ error: null, notice: null });
    const session = ++this.session;
    this.context = this.deps.audio();
    void this.context.resume().catch(() => undefined);
    void this.open(session);
  };

  private async open(session: number): Promise<void> {
    let stream: MediaStream;
    try {
      stream = await this.deps.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (error) {
      if (session !== this.session) return;
      const name = (error as { name?: string })?.name;
      return this.fail(name === "NotAllowedError" || name === "SecurityError" ? MESSAGES.denied : MESSAGES.noMic);
    }
    if (session !== this.session || !this.context) {
      for (const track of stream.getTracks()) track.stop();
      return;
    }
    if (!recorderType((type) => MediaRecorder.isTypeSupported(type))) {
      for (const track of stream.getTracks()) track.stop();
      return this.fail(MESSAGES.format);
    }
    this.stream = stream;
    for (const track of stream.getAudioTracks()) {
      track.enabled = !this.snapshot.muted;
      track.onended = () => session === this.session && this.fail(MESSAGES.lost);
    }
    const analyser = this.context.createAnalyser();
    analyser.fftSize = 1024;
    this.context.createMediaStreamSource(stream).connect(analyser);
    this.analyser = analyser;
    this.samples = new Float32Array(analyser.fftSize);
    this.spectrum = new Float32Array(analyser.frequencyBinCount);
    this.vad = freshVad();
    this.timer = setInterval(() => this.frame(session), FRAME_MS);
    this.listen();
    void this.prepareSpeech(session);
  }

  /**
   * The audio this browser really decodes (an acknowledgement, decoded, smallest format first: browsers' own
   * claims are not trusted), and the acknowledgements themselves when the API offers them. MP3 until then.
   */
  private async prepareSpeech(session: number): Promise<void> {
    const context = this.context;
    if (!context) return;
    const offered = await this.deps.config?.().catch(() => null);
    const load =
      this.deps.fetchAudio ??
      (async (url: string) => {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`${response.status}`);
        return response.arrayBuffer();
      });
    const clip = async (n: number, extension: string) =>
      spoken(await context.decodeAudioData(await load(`/voice/ack-${n}.${extension}`)));
    for (const [format, extension] of FORMATS) {
      try {
        const first = await clip(1, extension);
        const rest = offered?.ack ? await Promise.all(Array.from({ length: ACKS - 1 }, (_, n) => clip(n + 2, extension))) : [];
        if (session !== this.session) return;
        this.format = format;
        this.acks = offered?.ack ? [first, ...rest] : [];
        this.serverSpeech = Boolean(offered?.serverSpeech);
        return;
      } catch {
        if (session !== this.session) return; // else: the next format
      }
    }
  }

  /** The acknowledgement ("Okay.") the moment a question is sent, else the chime; the detector rests meanwhile. */
  private acknowledge(context: AudioContext): void {
    const clip = this.acks[this.ackCount++ % Math.max(1, this.acks.length)];
    if (!clip) {
      chime(context);
      return;
    }
    const source = context.createBufferSource();
    source.buffer = clip.buffer;
    source.connect(context.destination);
    Object.defineProperty(source, "padhaiAck", { value: true }); // the QA benchmark tells it from the answer
    source.start(0, clip.offset, clip.duration);
    this.ackEnd = context.currentTime + clip.duration;
    this.quietUntil = this.now() + clip.duration * 1000 + 150;
    this.timings.ack = this.now();
  }

  /** End the session: everything is released; a reply still being written finishes in the chat. */
  end = (): void => {
    const state = this.snapshot.state;
    if (state === "idle" || state === "ending") return;
    this.session += 1;
    this.turn += 1;
    this.move("ending");
    this.release();
    this.move("idle");
  };

  private release(): void {
    this.scheduler?.stop();
    this.scheduler = null;
    this.requests.abort();
    this.requests = new AbortController();
    this.dropRecorder();
    for (const stop of this.unwatch) stop();
    this.unwatch = [];
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    for (const track of this.stream?.getTracks() ?? []) {
      track.onended = null;
      track.stop();
    }
    this.stream = null;
    this.analyser = null;
    void this.context?.close().catch(() => undefined);
    this.context = null;
  }

  private fail(message: string): void {
    this.turn += 1;
    this.release();
    this.set({ error: message });
    this.move("error");
  }

  setMuted = (muted: boolean): void => {
    this.set({ muted });
    for (const track of this.stream?.getAudioTracks() ?? []) track.enabled = !muted;
    const state = this.snapshot.state;
    if (muted && state === "listening") {
      this.dropRecorder();
      this.move("muted");
    } else if (!muted && state === "muted") {
      this.listen();
    }
  };

  /** Stop the tutor (a tap, or the student starting to speak) and listen. */
  interrupt = (byVoice = false): void => {
    const state = this.snapshot.state;
    if (state !== "speaking" && state !== "thinking" && state !== "transcribing") return;
    this.timings.interrupted = this.now();
    this.turn += 1; // nothing of the old turn may land now
    this.scheduler?.stop();
    this.scheduler = null;
    this.timings.silent = this.now();
    record(this.timings);
    this.timings = {};
    for (const stop of this.unwatch) stop();
    this.unwatch = [];
    if (this.chat.getEntry(this.chatKey)?.stream) void this.chat.stop(this.chatKey);
    this.move("interrupted");
    if (byVoice && !this.snapshot.muted) {
      this.startRecorder(); // the student is already talking: their utterance ends at their next pause
      this.vad = { ...resetVad(this.vad), speaking: true };
      this.speechSince = this.now();
    } else {
      this.listen();
    }
  };

  // ------------------------------------------------------------------ listening
  private listen(): void {
    if (this.snapshot.muted) {
      this.dropRecorder();
      this.move("muted");
      return;
    }
    if (!this.move("listening")) return;
    this.vad = resetVad(this.vad);
    this.startRecorder();
  }

  private frame(session: number): void {
    if (session !== this.session || !this.analyser || !this.context) return;
    this.analyser.getFloatTimeDomainData(this.samples);
    this.analyser.getFloatFrequencyData(this.spectrum);
    const level = rms(this.samples);
    this.onLevel?.(level);
    if (this.snapshot.muted || this.now() < this.quietUntil) return;
    const state = this.snapshot.state;
    const mode = state === "speaking" || state === "thinking" ? "playback" : "listen";
    if (state !== "listening" && state !== "interrupted" && mode !== "playback") return;
    const { vad, event } = vadStep(this.vad, level, voiceBand(this.spectrum, this.context.sampleRate), mode);
    this.vad = vad;
    const now = this.now();
    if (event === "start") {
      if (mode === "playback") this.interrupt(true);
      else this.speechSince = now;
      return;
    }
    if (event === "end" || (vad.speaking && now - this.speechSince > MAX_UTTERANCE_MS)) {
      if (state === "listening" || state === "interrupted") void this.endUtterance();
      return;
    }
    if (this.recordedBytes > MAX_RECORDING_BYTES && (state === "listening" || state === "interrupted")) {
      if (vad.speaking) void this.endUtterance();
      else this.startRecorder();
      return;
    }
    // No speech for a while: begin the recording again, so it never carries a long silence.
    if (!vad.speaking && state === "listening" && now - this.recordingSince > IDLE_RECORDING_MS) this.startRecorder();
  }

  private startRecorder(): void {
    this.dropRecorder();
    if (!this.stream) return;
    const type = recorderType((candidate) => MediaRecorder.isTypeSupported(candidate));
    if (!type) {
      this.fail(MESSAGES.format);
      return;
    }
    const recorder = new MediaRecorder(this.stream, { mimeType: type, audioBitsPerSecond: 24_000 });
    this.recorded = [];
    this.recordedBytes = 0;
    this.recordingSince = this.now();
    recorder.ondataavailable = (event) => {
      if (recorder !== this.recorder || !event.data.size) return;
      this.recorded.push(event.data);
      this.recordedBytes += event.data.size;
    };
    this.recorder = recorder;
    recorder.start(250);
  }

  private dropRecorder(): void {
    const recorder = this.recorder;
    this.recorder = null;
    this.recorded = [];
    this.recordedBytes = 0;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  /** The recording so far, whole (the recorder's last data arrives with its stop). */
  private finishRecording(): Promise<{ audio: Blob; seconds: number } | null> {
    const recorder = this.recorder;
    if (!recorder) return Promise.resolve(null);
    this.recorder = null;
    const parts = this.recorded;
    const seconds = (this.now() - this.recordingSince) / 1000;
    return new Promise((resolve) => {
      recorder.ondataavailable = (event) => event.data.size && parts.push(event.data);
      recorder.onstop = () => resolve({ audio: new Blob(parts, { type: recorder.mimeType }), seconds });
      if (recorder.state === "inactive") resolve({ audio: new Blob(parts, { type: recorder.mimeType }), seconds });
      else recorder.stop();
    });
  }

  // ------------------------------------------------------------------ one turn
  private async endUtterance(): Promise<void> {
    const turn = ++this.turn;
    this.timings = { speechEnd: this.now() - END_MS };
    if (!this.move("transcribing")) return;
    const recording = await this.finishRecording();
    if (turn !== this.turn) return;
    if (!recording || recording.audio.size === 0) return this.listen();
    if (this.context) this.acknowledge(this.context);
    let text = "";
    try {
      text = (await this.deps.transcribe(recording.audio, recording.seconds, this.requests.signal)).text.trim();
    } catch (error) {
      if (turn !== this.turn) return;
      const code = error instanceof ApiError ? error.code : "network_error";
      if (code === "voice_unreadable") this.set({ notice: MESSAGES.notHeard });
      else this.set({ notice: describe(code) });
      return this.listen();
    }
    if (turn !== this.turn) return;
    this.timings.transcript = this.now();
    if (!text) {
      this.set({ notice: MESSAGES.notHeard });
      return this.listen();
    }
    this.set({ notice: null });
    await this.ask(text, turn);
  }

  private async ask(text: string, turn: number): Promise<void> {
    // The chat sends nothing while a reply streams (after an interruption, its stop is on the way).
    await this.untilIdle();
    if (turn !== this.turn) return;
    if (!this.move("thinking")) return;
    this.set({ expression: "neutral" });
    this.reply = null;
    this.finished = false;
    this.spoke = false;
    this.waiting = [];
    this.chunker = new SpeechChunker();
    this.planWaiting = this.serverSpeech;
    this.premade = new Map();
    this.firstWords = null;
    const signal = this.requests.signal;
    const out = this.context ? webAudio(this.context, () => this.ackEnd) : null;
    if (!out) return;
    this.scheduler = new SpeechScheduler(
      (sentence, chunkSignal) => {
        if (!this.reply) return Promise.reject(new Error("no reply"));
        if (!this.timings.firstSpeechRequest) this.timings.firstSpeechRequest = this.now();
        const premade = this.premade.get(sentence);
        if (premade) {
          this.premade.delete(sentence);
          return premade;
        }
        return this.deps.synthesize({ messageId: this.reply, text: sentence, format: this.format }, anySignal(signal, chunkSignal));
      },
      out,
      {
        onStart: () => {
          if (turn !== this.turn) return;
          if (!this.timings.firstAudio) this.timings.firstAudio = this.now();
          this.spoke = true;
          this.move("speaking");
        },
        onIdle: () => turn === this.turn && this.afterReply(),
        onIncomplete: () => {
          if (turn !== this.turn) return;
          this.set({ notice: MESSAGES.incomplete });
          this.afterReply();
        },
        onRoom: () => turn === this.turn && this.feed(turn),
      },
    );
    this.unwatch.push(this.chat.subscribe(this.chatKey, () => this.watch(turn)));
    const sent = this.chat.send(this.chatKey, text, [], { mode: "voice", speechFormat: this.format });
    this.watch(turn);
    await sent;
    if (turn !== this.turn) return;
    this.watch(turn);
    if (!this.reply) {
      // Refused before any reply (a reply still being written, busy, a limit, offline): the store put the words
      // back in the draft.
      const entry = this.chat.getEntry(this.chatKey);
      this.set({ notice: describe(entry?.stream ? "conflict" : (entry?.composerError?.code ?? "network_error")) });
      this.scheduler?.stop();
      this.listen();
    }
  }

  /** The reply this turn is waiting for: its id once the stream has it, then its words as they come. */
  private watch(turn: number): void {
    if (turn !== this.turn) return;
    const id = this.chat.getEntry(this.chatKey)?.stream?.assistantId ?? null;
    if (id && id !== this.reply) {
      this.reply = id;
      this.unwatch.push(this.chat.subscribeMessage(this.chatKey, id, () => this.feed(turn)));
      this.feed(turn);
    }
  }

  private feed(turn: number): void {
    if (turn !== this.turn || !this.reply || !this.chunker || !this.scheduler) return;
    const message = this.chat.getMessage(this.chatKey, this.reply);
    if (!message) return;
    const expression = message.metadata?.expression;
    if (expression && EXPRESSIONS.has(expression) && expression !== this.snapshot.expression) this.set({ expression });
    if (message.content && !this.timings.firstToken) this.timings.firstToken = this.now();
    const done = message.status !== "streaming";
    if (!this.takeFirstWords(message.metadata?.speech, done)) return;
    if (!this.finished) {
      this.waiting.push(...(done ? this.chunker.finish(message.content) : this.chunker.next(message.content)));
      if (done) {
        this.finished = true;
        this.timings.replyDone = this.now();
      }
    }
    while (this.waiting.length && this.scheduler.enqueue(this.waiting[0] as SpeechChunk)) this.waiting.shift();
    if (this.finished && !this.waiting.length) {
      this.scheduler.finish();
      if (message.status === "error") this.set({ notice: "The tutor couldn't finish this answer; what it wrote is in the chat." });
    }
  }

  /**
   * The reply's first words when the server speaks them (`serverSpeech`): the chunker waits until the server
   * says which words it took, then reads on after them; their audio comes with the reply (or, if the server's
   * speech failed, is made here). False while still waiting.
   */
  private takeFirstWords(speech: StreamSpeech | undefined, done: boolean): boolean {
    if (this.planWaiting) {
      // Every speech event names the words (a later one may be the first seen here).
      if (speech && speech.state !== "skipped" && typeof speech.chars === "number" && speech.text && this.chunker) {
        this.planWaiting = false;
        this.chunker.skip(speech.chars);
        let resolve: (audio: Promise<ArrayBuffer>) => void = () => {};
        this.premade.set(speech.text, new Promise<ArrayBuffer>((settle) => {
          resolve = (audio) => settle(audio);
        }));
        this.firstWords = { text: speech.text, resolve };
        this.waiting.push({ seq: 0, text: speech.text });
      } else if (speech?.state === "skipped" || done) {
        this.planWaiting = false;
      } else {
        return false;
      }
    }
    const first = this.firstWords;
    if (first && (speech?.state === "ready" || speech?.state === "failed")) {
      this.firstWords = null;
      const reply = this.reply;
      first.resolve(
        speech.state === "ready" && speech.audio
          ? Promise.resolve(bytes(speech.audio))
          : reply
            ? this.deps.synthesize({ messageId: reply, text: first.text, format: this.format }, this.requests.signal)
            : Promise.reject(new Error("no reply")),
      );
    }
    return true;
  }

  private afterReply(): void {
    record(this.timings);
    this.timings = {};
    for (const stop of this.unwatch) stop();
    this.unwatch = [];
    this.scheduler = null;
    this.listen();
  }

  private untilIdle(): Promise<void> {
    if (!this.chat.getEntry(this.chatKey)?.stream) return Promise.resolve();
    return new Promise((resolve) => {
      const timeout = setTimeout(done, STREAM_END_WAIT_MS);
      const stop = this.chat.subscribe(this.chatKey, () => {
        if (!this.chat.getEntry(this.chatKey)?.stream) done();
      });
      function done() {
        clearTimeout(timeout);
        stop();
        resolve();
      }
    });
  }
}

type Clip = { buffer: AudioBuffer; offset: number; duration: number };

/** Only the spoken part of a clip (its file has silence around the word): it starts at once and rests the detector less. */
function spoken(buffer: AudioBuffer): Clip {
  const data = buffer.getChannelData(0);
  let first = 0;
  while (first < data.length && Math.abs(data[first] ?? 0) < 0.01) first += 1;
  let last = data.length - 1;
  while (last > first && Math.abs(data[last] ?? 0) < 0.01) last -= 1;
  const pad = Math.floor(buffer.sampleRate * 0.03);
  const start = Math.max(0, first - pad);
  const end = Math.min(data.length, last + pad);
  return { buffer, offset: start / buffer.sampleRate, duration: Math.max(0.05, (end - start) / buffer.sampleRate) };
}

/**
 * A soft two-note chime when a question is sent: heard, the tutor is on it (the owner's choice, 2026-10-26, so the
 * wait is not silent). Not listened to: the detector rests while a question is transcribed.
 */
function chime(context: AudioContext): void {
  const at = context.currentTime;
  const gain = context.createGain();
  gain.connect(context.destination);
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(0.05, at + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.3);
  for (const [frequency, offset] of [
    [660, 0],
    [880, 0.09],
  ] as const) {
    const tone = context.createOscillator();
    tone.frequency.value = frequency;
    tone.connect(gain);
    tone.start(at + offset);
    tone.stop(at + 0.32);
  }
}

/** Base64 audio from the stream as bytes. */
function bytes(base64: string): ArrayBuffer {
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

/** One signal for a request that either the turn or its chunk may cancel. */
function anySignal(...signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController();
  for (const signal of signals) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return controller.signal;
}

function describe(code: string): string {
  switch (code) {
    case "rate_limited":
      return "That's a lot of questions at once. Please wait a moment, then speak again.";
    case "voice_busy":
    case "busy":
      return "Voice is busy right now. Please speak again in a moment.";
    case "voice_unavailable":
    case "service_unavailable":
      return "Voice isn't working right now. You can type your question in the chat.";
    case "network_error":
      return "You seem to be offline. Check your connection, then speak again.";
    case "conflict":
      return "A reply is still being written in this chat. Please wait a moment.";
    default:
      return MESSAGES.failed;
  }
}
