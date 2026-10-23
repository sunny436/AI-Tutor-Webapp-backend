import { describe, expect, test } from "bun:test";

import { type AudioOut, LIMITS, type Playable, SpeechScheduler } from "./scheduler";

/** A synthesizer whose requests the test answers (or fails) one by one, in any order. */
function synthesizer() {
  const calls: { text: string; signal: AbortSignal; resolve: (bytes: ArrayBuffer) => void; reject: (error: Error) => void }[] = [];
  const synthesize = (text: string, signal: AbortSignal) =>
    new Promise<ArrayBuffer>((resolve, reject) => calls.push({ text, signal, resolve, reject }));
  const answer = (text: string) =>
    calls.find((call) => call.text === text)?.resolve(new TextEncoder().encode(text).buffer as ArrayBuffer);
  const fail = (text: string) => calls.find((call) => call.text === text)?.reject(new Error("503"));
  return { calls, synthesize, answer, fail };
}

/** An output whose playback the test ends: what was started, in order, and stop() calls. */
function output() {
  const started: string[] = [];
  const stopped: string[] = [];
  const ends: Record<string, () => void> = {};
  let time = 0;
  const out: AudioOut = {
    decode: async (bytes) => ({ duration: 1, bytes: bytes.byteLength, text: new TextDecoder().decode(bytes) }) as Playable,
    play(audio, at) {
      const text = (audio as Playable & { text: string }).text;
      started.push(text);
      let done: () => void = () => {};
      const ended = new Promise<void>((resolve) => {
        done = resolve;
      });
      ends[text] = () => {
        time = Math.max(time, at + audio.duration);
        done();
      };
      return {
        stop: () => {
          stopped.push(text);
          done();
        },
        ended,
      };
    },
    now: () => time,
  };
  return { out, started, stopped, end: (text: string) => ends[text]?.() };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const chunk = (seq: number) => ({ seq, text: `chunk ${seq}` });

describe("speech plays in order, bounded, and stops at once (scheduler.ts)", () => {
  test("one request at a time with the next ready ahead; played in sequence", async () => {
    const synth = synthesizer();
    const audio = output();
    const heard: number[] = [];
    const scheduler = new SpeechScheduler(synth.synthesize, audio.out, { onStart: (seq) => heard.push(seq) });
    for (const seq of [0, 1, 2]) scheduler.enqueue(chunk(seq));
    expect(synth.calls.map((call) => call.text)).toEqual(["chunk 0"]); // 1 in flight
    synth.answer("chunk 0");
    await tick();
    expect(audio.started).toEqual(["chunk 0"]);
    expect(synth.calls.map((call) => call.text)).toEqual(["chunk 0", "chunk 1"]); // the prefetch
    synth.answer("chunk 1");
    await tick();
    expect(audio.started).toEqual(["chunk 0", "chunk 1"]); // scheduled back to back
    expect(synth.calls).toHaveLength(2); // chunk 2 waits: two ahead is the lookahead
    audio.end("chunk 0");
    await tick();
    expect(synth.calls.map((call) => call.text)).toEqual(["chunk 0", "chunk 1", "chunk 2"]);
    expect(heard).toEqual([0, 1]);
  });

  test("out-of-order completion still plays in order", async () => {
    const synth = synthesizer();
    const audio = output();
    const scheduler = new SpeechScheduler(synth.synthesize, audio.out, {}, { ...LIMITS, maxInFlight: 2 });
    for (const seq of [0, 1]) scheduler.enqueue(chunk(seq));
    synth.answer("chunk 1");
    await tick();
    expect(audio.started).toEqual([]); // 1 is ready, but 0 comes first
    synth.answer("chunk 0");
    await tick();
    expect(audio.started).toEqual(["chunk 0", "chunk 1"]);
  });

  test("stop: silence now, requests aborted, nothing late is ever played, memory released", async () => {
    const synth = synthesizer();
    const audio = output();
    const scheduler = new SpeechScheduler(synth.synthesize, audio.out, {}, { ...LIMITS, maxInFlight: 2 });
    for (const seq of [0, 1, 2]) scheduler.enqueue(chunk(seq));
    synth.answer("chunk 0");
    await tick();
    expect(audio.started).toEqual(["chunk 0"]);
    scheduler.stop();
    expect(audio.stopped).toEqual(["chunk 0"]);
    expect(synth.calls.every((call) => call.signal.aborted)).toBe(true);
    synth.answer("chunk 1"); // arrives after the interruption
    await tick();
    expect(audio.started).toEqual(["chunk 0"]);
    expect(scheduler.states).toEqual(["cancelled", "cancelled", "cancelled"]);
    expect(scheduler.decodedBytes).toBe(0);
    expect(scheduler.enqueue(chunk(3))).toBe(false);
  });

  test("a chunk that fails ends the speech there: what came before plays, nothing after, and it says so", async () => {
    const synth = synthesizer();
    const audio = output();
    let incomplete = 0;
    let idle = 0;
    const scheduler = new SpeechScheduler(synth.synthesize, audio.out, {
      onIncomplete: () => incomplete++,
      onIdle: () => idle++,
    });
    for (const seq of [0, 1, 2]) scheduler.enqueue(chunk(seq));
    scheduler.finish();
    synth.answer("chunk 0");
    await tick();
    synth.fail("chunk 1");
    await tick();
    expect(incomplete).toBe(0); // chunk 0 is still playing
    audio.end("chunk 0");
    await tick();
    expect(scheduler.states).toEqual(["completed", "failed", "cancelled"]);
    expect(audio.started).toEqual(["chunk 0"]);
    expect(synth.calls.map((call) => call.text)).toEqual(["chunk 0", "chunk 1"]); // chunk 2 never made
    expect([incomplete, idle]).toEqual([1, 0]);
  });

  test("everything played after finish(): idle once, and decoded audio released", async () => {
    const synth = synthesizer();
    const audio = output();
    let idle = 0;
    const scheduler = new SpeechScheduler(synth.synthesize, audio.out, { onIdle: () => idle++ });
    scheduler.enqueue(chunk(0));
    scheduler.finish();
    synth.answer("chunk 0");
    await tick();
    expect(scheduler.decodedBytes).toBeGreaterThan(0);
    audio.end("chunk 0");
    await tick();
    expect([idle, scheduler.decodedBytes]).toEqual([1, 0]);
  });

  test("bounded: text waiting (enqueue refuses, then room) and decoded audio held", async () => {
    const synth = synthesizer();
    const audio = output();
    let room = 0;
    const scheduler = new SpeechScheduler(
      synth.synthesize,
      audio.out,
      { onRoom: () => room++ },
      { ...LIMITS, maxQueuedChars: 10 },
    );
    expect(scheduler.enqueue(chunk(0))).toBe(true); // synthesizing at once: not waiting
    expect(scheduler.enqueue(chunk(1))).toBe(true); // 7 characters waiting
    expect(scheduler.enqueue(chunk(2))).toBe(false); // 7 + 7 would pass 10
    expect(room).toBe(0);
    synth.answer("chunk 0");
    await tick();
    expect(room).toBe(1); // chunk 1 started: there is room again

    const tight = new SpeechScheduler(synth.synthesize, output().out, {}, { ...LIMITS, maxInFlight: 2, maxDecodedBytes: 1 });
    tight.enqueue({ seq: 0, text: "a" });
    tight.enqueue({ seq: 1, text: "b" });
    synth.answer("a");
    await tick();
    expect(synth.calls.filter((call) => call.text === "b")).toHaveLength(1); // started before "a" was decoded
  });
});
