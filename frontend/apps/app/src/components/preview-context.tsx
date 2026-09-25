"use client";

import { type ReactNode, createContext, useContext } from "react";

/**
 * Whether preview UI may render (see lib/preview.ts). Decided on the server by
 * the `(app)` layout and handed down, so a client component never reads the
 * environment itself. Defaults to false: a component rendered outside the
 * provider shows no preview UI.
 */
const PreviewContext = createContext(false);

export function PreviewProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  return <PreviewContext.Provider value={enabled}>{children}</PreviewContext.Provider>;
}

export function usePreview(): boolean {
  return useContext(PreviewContext);
}
