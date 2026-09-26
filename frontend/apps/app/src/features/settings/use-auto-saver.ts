"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { describeError } from "@/lib/api/errors";
import { AutoSaver, type Versioned } from "./auto-saver";

/**
 * A server resource saved as it is changed (see AutoSaver). `load` runs once on mount; while
 * it runs, `value` is null. Failures are told with a toast in the app's own words.
 */
export function useAutoSaver<T extends Versioned>(options: {
  load: () => Promise<T>;
  save: (version: number, changes: Partial<T>) => Promise<T>;
  onSaved?: (value: T) => void;
  initial?: T | null;
}) {
  const [saver] = useState(
    () =>
      new AutoSaver<T>({
        save: options.save,
        onSaved: options.onSaved,
        onError: (error) => toast.error(`Couldn't save that. ${describeError(error).message}`),
      }),
  );
  const [loadError, setLoadError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const value = useSyncExternalStore(
    saver.subscribe,
    () => saver.view,
    () => options.initial ?? null,
  );

  // Loads once per attempt (the options object is new on every render).
  useEffect(() => {
    let cancelled = false;
    if (options.initial && attempt === 0) {
      saver.load(options.initial);
      return;
    }
    setLoadError(null);
    options
      .load()
      .then((loaded) => !cancelled && saver.load(loaded))
      .catch((error) => !cancelled && setLoadError(error));
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // Leaving the page sends what is still waiting rather than dropping it.
  useEffect(() => () => void saver.flush(), [saver]);

  return {
    value,
    change: (changes: Partial<T>) => saver.change(changes),
    saving: saver.saving,
    loadError,
    retry: () => setAttempt((count) => count + 1),
  };
}
