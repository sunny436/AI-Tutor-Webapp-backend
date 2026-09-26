"use client";

import { useTheme } from "next-themes";
import { type ReactNode, createContext, useContext, useEffect } from "react";

import { useAutoSaver } from "@/features/settings/use-auto-saver";
import { getAppearance, updateAppearance } from "@/lib/api/preferences";
import type { Appearance, AppearanceValues } from "@/lib/api/types";
import { applyAttributes, attributesFor, cacheAttributes } from "@/lib/appearance";

type AppearanceContextValue = {
  /** Null until known (the server's value, or its first load). */
  appearance: Appearance | null;
  change: (values: Partial<AppearanceValues>) => void;
};

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

/**
 * The signed-in user's appearance (GET/PATCH /v1/me/appearance), the same on every device.
 * One auto-saver for the whole app, so the Settings page and the sidebar's theme switcher can
 * never save over each other. It applies the attributes the design tokens read, keeps
 * next-themes on the saved theme, and refreshes the cache the pre-paint script uses.
 */
export function AppearanceProvider({ initial, children }: { initial: Appearance | null; children: ReactNode }) {
  const { theme, setTheme } = useTheme();
  const { value, change } = useAutoSaver<Appearance>({
    initial,
    load: getAppearance,
    save: (version, set) => updateAppearance({ version, set }),
  });

  useEffect(() => {
    if (!value) return;
    const attributes = attributesFor(value);
    applyAttributes(document.documentElement, attributes);
    cacheAttributes(attributes);
  }, [value]);

  useEffect(() => {
    if (value && theme !== value.theme) setTheme(value.theme);
  }, [value?.theme, theme, setTheme, value]);

  return <AppearanceContext.Provider value={{ appearance: value, change }}>{children}</AppearanceContext.Provider>;
}

/** Inside the signed-in app; `null` elsewhere (sign-in pages keep next-themes on its own). */
export function useAppearance(): AppearanceContextValue | null {
  return useContext(AppearanceContext);
}
