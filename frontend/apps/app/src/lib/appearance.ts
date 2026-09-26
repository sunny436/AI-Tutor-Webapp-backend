/**
 * Appearance (GET/PATCH /v1/me/appearance) as attributes on <html>, which the design tokens
 * read (packages/ui/src/globals.css): `data-font-size`, `data-contrast`, `data-motion` and
 * `data-reading`. The colour theme stays with next-themes (the `dark` class).
 *
 * The API is the source of truth. A copy of the ATTRIBUTES (not the settings) is cached in
 * localStorage so the pre-paint script can set them before the first paint on the next visit,
 * without knowing how settings map to attributes; the server's value then reconciles.
 */

import type { AppearanceValues } from "@/lib/api/types";

export const APPEARANCE_CACHE_KEY = "padhai.appearance";

export type AppearanceAttributes = Record<
  "data-font-size" | "data-contrast" | "data-motion" | "data-reading",
  string | null
>;

export function attributesFor(appearance: Omit<AppearanceValues, "theme" | "showStreak">): AppearanceAttributes {
  return {
    "data-font-size": appearance.fontSize === "medium" ? null : appearance.fontSize,
    "data-contrast": appearance.highContrast ? "high" : null,
    "data-motion": appearance.reduceMotion ? "reduce" : null,
    "data-reading": appearance.readingComfort ? "comfort" : null,
  };
}

export function applyAttributes(root: HTMLElement, attributes: AppearanceAttributes): void {
  for (const [name, value] of Object.entries(attributes)) {
    if (value === null) root.removeAttribute(name);
    else root.setAttribute(name, value);
  }
}

export function cacheAttributes(attributes: AppearanceAttributes | null): void {
  try {
    if (attributes) window.localStorage.setItem(APPEARANCE_CACHE_KEY, JSON.stringify(attributes));
    else window.localStorage.removeItem(APPEARANCE_CACHE_KEY);
  } catch {
    // storage unavailable: the server's value still applies after load
  }
}

/** Runs before the first paint (inline in the root layout). Only sets known attributes. */
export const PREPAINT_SCRIPT = `(function(){try{var a=JSON.parse(localStorage.getItem(${JSON.stringify(
  APPEARANCE_CACHE_KEY,
)})||"null");if(!a)return;var r=document.documentElement;["data-font-size","data-contrast","data-motion","data-reading"].forEach(function(n){var v=a[n];if(typeof v==="string"&&/^[a-z_]{1,16}$/.test(v))r.setAttribute(n,v);});}catch(e){}})();`;
