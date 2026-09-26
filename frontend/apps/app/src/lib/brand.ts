/**
 * The product's brand, in one place.
 *
 * Everything that shows the brand reads it from here: the name in titles and
 * copy, the two-tone wordmark ("Padh" + "AI"), the tagline, and the mark — ONE
 * image file, also used as the favicon. Replacing the logo means replacing that
 * file (and `markSrc` if its name changes); no component draws the logo itself.
 *
 * The backend has its own `APP_NAME` (its sign-up and reset emails say "Your
 * <name> verification code"). It is set in the API's environment, not here; set
 * it to the same name so the inbox and the app agree.
 */
export const BRAND = {
  name: "PadhAI",
  wordmark: { lead: "Padh", accent: "AI" },
  tagline: "Your Questions. Your Tutor. Your Way.",
  description: "PadhAI, your personal AI tutor.",
  /** Served from `public/`. A square image that carries its own background. */
  markSrc: "/brand/padhai-mark.svg",
} as const;

export const APP_NAME = BRAND.name;
