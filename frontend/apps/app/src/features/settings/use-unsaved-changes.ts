"use client";

import { useEffect, useRef } from "react";

import { navigationGuard } from "@/features/navigation/navigation-guard";

export { UNSAVED_MESSAGE } from "@/features/navigation/navigation-guard";

/**
 * While `dirty`, leaving loses the edit: the student is asked first, however they leave (a link,
 * Close, search, log out, reload or closing the tab, the browser's Back and Forward). The one
 * guard for the whole page does the asking (features/navigation/navigation-guard.ts).
 */
export function useUnsavedChanges(dirty: boolean): void {
  const source = useRef({}).current;
  useEffect(() => {
    navigationGuard.setDirty(source, dirty);
  }, [source, dirty]);
  useEffect(() => () => navigationGuard.setDirty(source, false), [source]);
}
