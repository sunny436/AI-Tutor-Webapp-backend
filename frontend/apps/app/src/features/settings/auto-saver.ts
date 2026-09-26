/**
 * Saves toggle-style settings (appearance, notifications) as the user flips them.
 *
 * - **Batched:** changes made within `delay` ms go out as ONE versioned PATCH.
 * - **Shown at once:** `view` is the confirmed value with every unsaved and in-flight change
 *   laid over it, so a switch moves when it is clicked, not when the server answers.
 * - **Rolled back** on failure: the failed batch disappears from `view`, `onError` is told.
 * - **Rebased once** on 409 `version_conflict`: another tab or device saved first. The
 *   conflict carries the resource as it is now; the batch is re-sent onto that version once.
 *   (Toggles are independent fields, so re-applying the user's own change is what they meant.)
 *
 * No React here: the hook in use-auto-saver.ts subscribes to it; tests drive it directly.
 */

import { ApiError } from "@/lib/api/errors";

export type Versioned = { version: number };

export type AutoSaverOptions<T extends Versioned> = {
  save: (version: number, changes: Partial<T>) => Promise<T>;
  onError?: (error: unknown) => void;
  onSaved?: (value: T) => void;
  delay?: number;
  /** Test seam for timers. */
  schedule?: (run: () => void, ms: number) => () => void;
};

const defaultSchedule = (run: () => void, ms: number) => {
  const timer = setTimeout(run, ms);
  return () => clearTimeout(timer);
};

export class AutoSaver<T extends Versioned> {
  private confirmed: T | null = null;
  private inflight: Partial<T> = {};
  private pending: Partial<T> = {};
  private busy = false;
  private cancelTimer: (() => void) | null = null;
  private listeners = new Set<() => void>();
  private snapshot: T | null = null;

  constructor(private readonly options: AutoSaverOptions<T>) {}

  /** The value to show: confirmed, then in-flight, then unsent changes. */
  get view(): T | null {
    return this.snapshot;
  }

  get saving(): boolean {
    return this.busy || Object.keys(this.pending).length > 0;
  }

  /** Start from (or replace with) a value read from the server. */
  load(value: T): void {
    this.confirmed = value;
    this.emit();
  }

  change(values: Partial<T>): void {
    this.pending = { ...this.pending, ...values };
    this.emit();
    this.cancelTimer?.();
    this.cancelTimer = (this.options.schedule ?? defaultSchedule)(() => {
      this.cancelTimer = null;
      void this.flush();
    }, this.options.delay ?? 400);
  }

  /**
   * Send what is waiting now (the timer calls it too). Every caller gets the same running
   * save, which resolves once nothing is left to send, including changes made meanwhile.
   */
  flush(): Promise<void> {
    if (!this.running) {
      this.running = this.drain().finally(() => {
        this.running = null;
      });
    }
    return this.running;
  }

  private running: Promise<void> | null = null;

  private async drain(): Promise<void> {
    while (this.confirmed && Object.keys(this.pending).length > 0) {
      this.busy = true;
      this.inflight = this.pending;
      this.pending = {};
      this.emit();
      try {
        this.confirmed = await this.send(this.confirmed.version, this.inflight, true);
        this.options.onSaved?.(this.confirmed);
      } catch (error) {
        this.options.onError?.(error);
      } finally {
        this.inflight = {};
        this.busy = false;
        this.emit();
      }
    }
  }

  private async send(version: number, changes: Partial<T>, mayRebase: boolean): Promise<T> {
    try {
      return await this.options.save(version, changes);
    } catch (error) {
      if (mayRebase && error instanceof ApiError && error.code === "version_conflict" && isVersioned(error.current)) {
        this.confirmed = error.current as T;
        this.emit();
        return await this.send(this.confirmed.version, changes, false);
      }
      throw error;
    }
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private emit(): void {
    this.snapshot = this.confirmed ? { ...this.confirmed, ...this.inflight, ...this.pending } : null;
    for (const listener of this.listeners) listener();
  }
}

function isVersioned(value: unknown): value is Versioned {
  return typeof value === "object" && value !== null && typeof (value as Versioned).version === "number";
}
