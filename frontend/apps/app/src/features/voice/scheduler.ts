/**
 * One reply's speech, in order: its chunks (speech-text.ts) become audio one OllaLink request at a time, with
 * the next one ready ahead, and play back to back by sequence number however their requests complete. Stopped
 * at once (an interruption, the end of the session), and nothing late from a stopped reply is ever played.
 *
 * Each chunk is pending → synthesizing → ready → playing → completed, or failed / cancelled. Bounded, each on
 * its own: requests at once (maxInFlight), chunks made ready ahead of the one playing (lookahead), text waiting
 * to be spoken (maxQueuedChars: `enqueue` refuses more), and decoded audio held (maxDecodedBytes). A chunk that
 * cannot be spoken ends this reply's speech there, after what came before it; the rest is never played out of
 * order, and `onIncomplete` says so (the whole reply is in the chat).
 */

export type ChunkState = "pending" | "synthesizing" | "ready" | "playing" | "completed" | "failed" | "cancelled";

export type Playable = { duration: number; bytes: number };

/** Where speech plays: Web Audio in the browser (use-voice-session.ts), a fake in tests. */
export interface AudioOut {
  decode(bytes: ArrayBuffer): Promise<Playable>;
  /** Start `audio` at `at` (seconds on the output's clock). `ended` settles once it has played or was stopped. */
  play(audio: Playable, at: number): { stop(): void; ended: Promise<void> };
  now(): number;
}

export type SchedulerEvents = {
  /** A chunk is starting to play: the student hears it now. */
  onStart?: (seq: number, text: string) => void;
  /** Everything was played (after `finish`). */
  onIdle?: () => void;
  /** A chunk could not be spoken: speech stopped there, the rest is in the chat. */
  onIncomplete?: () => void;
  /** Text waiting to be spoken fell below the limit: `enqueue` takes more again. */
  onRoom?: () => void;
};

export type SchedulerLimits = { maxInFlight: number; lookahead: number; maxQueuedChars: number; maxDecodedBytes: number };
export const LIMITS: SchedulerLimits = { maxInFlight: 1, lookahead: 2, maxQueuedChars: 2000, maxDecodedBytes: 4 * 1024 * 1024 };

type Chunk = { seq: number; text: string; state: ChunkState; audio?: Playable; announced?: boolean };

export class SpeechScheduler {
  private readonly chunks: Chunk[] = [];
  private readonly controller = new AbortController();
  private readonly playing = new Set<{ stop(): void }>();
  private inFlight = 0;
  private decoded = 0;
  private finished = false;
  private stopped = false;
  private ended = false; // onIdle or onIncomplete was called
  private refused = false; // enqueue said no: tell the caller when there is room
  private next = 0; // index of the next chunk to schedule
  private clock = 0; // when the audio scheduled so far ends

  constructor(
    private readonly synthesize: (text: string, signal: AbortSignal) => Promise<ArrayBuffer>,
    private readonly out: AudioOut,
    private readonly events: SchedulerEvents = {},
    private readonly limits: SchedulerLimits = LIMITS,
  ) {}

  /** The text still to be synthesized. */
  get queuedChars(): number {
    return this.chunks.reduce((sum, chunk) => sum + (chunk.state === "pending" ? chunk.text.length : 0), 0);
  }

  get states(): ChunkState[] {
    return this.chunks.map((chunk) => chunk.state);
  }

  get decodedBytes(): number {
    return this.decoded;
  }

  get isStopped(): boolean {
    return this.stopped;
  }

  /** Add the next chunk, in order. False (nothing added) when the text waiting would pass maxQueuedChars. */
  enqueue(chunk: { seq: number; text: string }): boolean {
    if (this.stopped || this.finished) return false;
    if (this.queuedChars > 0 && this.queuedChars + chunk.text.length > this.limits.maxQueuedChars) {
      this.refused = true;
      return false;
    }
    this.chunks.push({ ...chunk, state: "pending" });
    this.pump();
    return true;
  }

  /** No more chunks for this reply. */
  finish(): void {
    this.finished = true;
    this.settle();
  }

  /** Silence now: stop what plays, abort what is being made, play nothing that arrives later. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.controller.abort();
    for (const source of this.playing) source.stop();
    this.playing.clear();
    for (const chunk of this.chunks) {
      if (chunk.state !== "completed" && chunk.state !== "failed") chunk.state = "cancelled";
      chunk.audio = undefined;
    }
    this.decoded = 0;
  }

  /** Start making audio for the next pending chunks, within every limit. */
  private pump(): void {
    if (this.stopped) return;
    const firstUnplayed = this.chunks.findIndex((chunk) => chunk.state !== "completed");
    if (firstUnplayed === -1) return;
    for (let index = firstUnplayed; index < Math.min(this.chunks.length, firstUnplayed + this.limits.lookahead); index++) {
      if (this.inFlight >= this.limits.maxInFlight || this.decoded >= this.limits.maxDecodedBytes) return;
      const chunk = this.chunks[index] as Chunk;
      if (chunk.state === "failed") return; // nothing after a chunk that could not be spoken
      if (chunk.state === "pending") void this.make(chunk);
    }
  }

  private async make(chunk: Chunk): Promise<void> {
    chunk.state = "synthesizing";
    this.inFlight += 1;
    if (this.refused && this.queuedChars < this.limits.maxQueuedChars) {
      this.refused = false;
      this.events.onRoom?.();
    }
    try {
      const bytes = await this.synthesize(chunk.text, this.controller.signal);
      if (this.stopped) return;
      const audio = await this.out.decode(bytes);
      if (this.stopped) return;
      chunk.audio = audio;
      chunk.state = "ready";
      this.decoded += audio.bytes;
    } catch {
      if (this.stopped) return;
      chunk.state = "failed";
      // Nothing after it is ever played, so nothing after it is made.
      for (const later of this.chunks) if (later.seq > chunk.seq && later.state === "pending") later.state = "cancelled";
    } finally {
      this.inFlight -= 1;
      if (!this.stopped) {
        this.schedule();
        this.pump();
        this.settle();
      }
    }
  }

  /** Play ready chunks in order, back to back, the current one and the one after it. */
  private schedule(): void {
    while (!this.stopped && this.playing.size < 2) {
      const chunk = this.chunks[this.next];
      if (!chunk || chunk.state !== "ready" || !chunk.audio) return;
      const at = Math.max(this.out.now(), this.clock);
      const source = this.out.play(chunk.audio, at);
      chunk.state = "playing";
      this.clock = at + chunk.audio.duration;
      this.next += 1;
      this.playing.add(source);
      // Said to have started when it starts: now, or when the one before it ends (or its time comes).
      const startsIn = Math.max(0, (at - this.out.now()) * 1000);
      if (startsIn < 5) this.announce(chunk);
      else setTimeout(() => this.announce(chunk), startsIn);
      void source.ended.then(() => {
        this.playing.delete(source);
        if (this.stopped || chunk.state !== "playing") return;
        chunk.state = "completed";
        const following = this.chunks[this.chunks.indexOf(chunk) + 1];
        if (following?.state === "playing") this.announce(following);
        this.decoded -= chunk.audio?.bytes ?? 0;
        chunk.audio = undefined;
        this.schedule();
        this.pump();
        this.settle();
      });
    }
  }

  private announce(chunk: Chunk): void {
    if (this.stopped || chunk.announced) return;
    chunk.announced = true;
    this.events.onStart?.(chunk.seq, chunk.text);
  }

  /** Done: everything played (onIdle), or speech ended at a chunk that failed (onIncomplete). */
  private settle(): void {
    if (this.stopped || this.ended || this.playing.size > 0) return;
    const failedAt = this.chunks.findIndex((chunk) => chunk.state === "failed");
    if (failedAt !== -1 && this.chunks.slice(0, failedAt).every((chunk) => chunk.state === "completed")) {
      this.ended = true;
      this.events.onIncomplete?.();
      return;
    }
    if (this.finished && this.chunks.every((chunk) => chunk.state === "completed")) {
      this.ended = true;
      this.events.onIdle?.();
    }
  }
}
