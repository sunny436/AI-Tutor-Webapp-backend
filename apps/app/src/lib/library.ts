/**
 * The published knowledge base.
 *
 * Reads a COMMITTED JSON file, not the filesystem. No `fs`, no path walking, and
 * nothing outside this app's own tree — which is what lets the frontend build and
 * run in a repository that contains no Python at all.
 *
 * HOW THE ONE SOURCE OF TRUTH IS STILL ONE
 * `src/content/library.json` is generated from `backend-python/data/knowledge/*.md`
 * by `scripts/generate-library.mjs`. That matters because the FILENAME IS THE
 * CITATION: per `backend-python/docs/knowledge-format.md`, an answer citing
 * `acidity.md` and the page at `/library/acidity` have to be the same document, or
 * the product's central claim — that every plan is traceable to a note you can
 * read — quietly stops being true.
 *
 * So the file is not a copy anybody maintains by hand. `library.test.ts` rebuilds
 * it from the notes and fails if the committed version differs, which turns drift
 * into a failing test and a visible diff rather than a page that disagrees with the
 * answer that cited it.
 *
 * THE CONTENT IS HINGLISH, AND THAT IS CORRECT
 * The people searching "khatti dakar ka ilaj" are the readers. It does mean these
 * pages must not claim to be English: the right BCP-47 tag for romanised Hindi is
 * `hi-Latn`, and telling a search engine otherwise competes them against the wrong
 * queries. See `LIBRARY_LANG`.
 */

import notes from "@/content/library.json";

/** Romanised Hindi. Not "en", and not "hi" — that would imply Devanagari. */
export const LIBRARY_LANG = "hi-Latn";

/** The eight headings every note carries. Verified across all 29. */
export const SECTION_ORDER = [
  "What It Is",
  "Root Cause",
  "Changes To Make",
  "Food Chart",
  "Daily Routine",
  "Yoga & Breathing",
  "Home Remedies",
  "When To See A Doctor",
] as const;

export type Section = { heading: string; body: string };

export type Note = {
  /** `acidity` — the filename stem, and the citation identifier. */
  slug: string;
  /** `acidity.md` — exactly what a citation names. */
  filename: string;
  /** From `topic:`. The page's h1 and title. */
  topic: string;
  /** From `aliases:`. Trilingual search terms the author wrote by hand. */
  aliases: string[];
  sections: Section[];
  /** `## What It Is`, used as the lede and the meta description. */
  summary: string;
};

/** Every publishable note, alphabetical by topic. */
export function allNotes(): Note[] {
  return notes as Note[];
}

export function noteBySlug(slug: string): Note | undefined {
  return allNotes().find((note) => note.slug === slug);
}

/** ~150 chars of plain text, for `<meta name="description">`. */
export function metaDescription(note: Note): string {
  const text = note.summary.replace(/\s+/g, " ").trim();
  return text.length <= 155 ? text : `${text.slice(0, 152).trimEnd()}…`;
}

/**
 * The safety section, which is never collapsed and never optional.
 *
 * `ALWAYS_INCLUDED` in `consult/sections.py` forces this into every generated
 * plan for the same reason. It genuinely matters: these notes tell people that
 * blood in vomit, black stools or chest pain radiating to the jaw need a doctor,
 * not a diet change.
 */
export function doctorSection(note: Note): Section | undefined {
  return note.sections.find((s) => s.heading === "When To See A Doctor");
}
