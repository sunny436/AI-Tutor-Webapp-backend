import { describe, expect, test } from "bun:test";

import { ApiError } from "@/lib/api/errors";
import { AutoSaver } from "./auto-saver";

type Prefs = { version: number; a: boolean; b: boolean };

function manualTimers() {
  const due: (() => void)[] = [];
  return {
    schedule: (run: () => void) => {
      due.push(run);
      return () => {
        const index = due.indexOf(run);
        if (index >= 0) due.splice(index, 1);
      };
    },
    fire: () => due.splice(0).forEach((run) => run()),
    pending: () => due.length,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return { promise, resolve, reject };
}

describe("AutoSaver", () => {
  test("changes show at once and go out as one versioned batch", async () => {
    const calls: [number, Partial<Prefs>][] = [];
    const timers = manualTimers();
    const saver = new AutoSaver<Prefs>({
      schedule: timers.schedule,
      save: async (version, changes) => {
        calls.push([version, changes]);
        return { version: version + 1, a: true, b: true };
      },
    });
    saver.load({ version: 3, a: false, b: false });
    saver.change({ a: true });
    saver.change({ b: true });
    expect(saver.view).toEqual({ version: 3, a: true, b: true });
    expect(timers.pending()).toBe(1); // the second change restarted the one timer
    timers.fire();
    await saver.flush();
    expect(calls).toEqual([[3, { a: true, b: true }]]);
    expect(saver.view).toEqual({ version: 4, a: true, b: true });
    expect(saver.saving).toBe(false);
  });

  test("a failed save rolls the change back and reports it", async () => {
    const errors: unknown[] = [];
    const saver = new AutoSaver<Prefs>({
      schedule: manualTimers().schedule,
      onError: (error) => errors.push(error),
      save: async () => {
        throw new ApiError(503, "service_unavailable");
      },
    });
    saver.load({ version: 1, a: false, b: false });
    saver.change({ a: true });
    await saver.flush();
    expect(saver.view).toEqual({ version: 1, a: false, b: false });
    expect((errors[0] as ApiError).code).toBe("service_unavailable");
  });

  test("a version conflict is rebased once onto the current value", async () => {
    const calls: number[] = [];
    const saver = new AutoSaver<Prefs>({
      schedule: manualTimers().schedule,
      save: async (version, changes) => {
        calls.push(version);
        if (version === 1) {
          throw new ApiError(409, "version_conflict", { current: { version: 5, a: false, b: true } });
        }
        return { version: version + 1, a: false, b: true, ...changes };
      },
    });
    saver.load({ version: 1, a: false, b: false });
    saver.change({ a: true });
    await saver.flush();
    expect(calls).toEqual([1, 5]);
    // The other device's `b` is kept; this device's `a` is applied on top.
    expect(saver.view).toEqual({ version: 6, a: true, b: true });
  });

  test("a second conflict is not retried forever", async () => {
    let calls = 0;
    const errors: unknown[] = [];
    const saver = new AutoSaver<Prefs>({
      schedule: manualTimers().schedule,
      onError: (error) => errors.push(error),
      save: async () => {
        calls += 1;
        throw new ApiError(409, "version_conflict", { current: { version: 10 + calls, a: false, b: false } });
      },
    });
    saver.load({ version: 1, a: false, b: false });
    saver.change({ a: true });
    await saver.flush();
    expect(calls).toBe(2);
    expect(errors).toHaveLength(1);
    expect(saver.view).toEqual({ version: 11, a: false, b: false });
  });

  test("changes made while a save is in flight go out next, not lost", async () => {
    const first = deferred<Prefs>();
    const calls: Partial<Prefs>[] = [];
    const saver = new AutoSaver<Prefs>({
      schedule: manualTimers().schedule,
      save: (version, changes) => {
        calls.push(changes);
        return calls.length === 1 ? first.promise : Promise.resolve({ version: version + 1, a: true, b: true });
      },
    });
    saver.load({ version: 1, a: false, b: false });
    saver.change({ a: true });
    const flushing = saver.flush();
    saver.change({ b: true });
    expect(saver.view).toEqual({ version: 1, a: true, b: true });
    first.resolve({ version: 2, a: true, b: false });
    await flushing;
    expect(calls).toEqual([{ a: true }, { b: true }]);
    expect(saver.view).toEqual({ version: 3, a: true, b: true });
  });
});
