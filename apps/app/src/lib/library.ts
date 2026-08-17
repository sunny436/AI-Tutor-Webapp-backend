/**
 * The published knowledge base.
 *
 * SERVER ONLY, and read at BUILD TIME. Uses `fs`, so importing it from a client
 * component will fail the build — which is the correct failure.
 *
 * WHY THESE ARE NOT COPIED INTO THIS APP
 * The notes are read from `backend-python/data/knowledge/`, the same files the
 * retriever searches. Per `backend-python/docs/knowledge-format.md` the FILENAME
 * IS THE CITATION: an answer that cites `acidity.md` and the page published at
 * `/library/acidity` have to be the same document, or the product's whole claim —
 * that every plan is traceable to a note you can read — quietly stops being true.
 * A copy would let the two drift apart with nothing to detect it.
 *
 * THE CONTENT IS HINGLISH, AND THAT IS CORRECT
 * The people searching "khatti dakar ka ilaj" are the readers. It does mean these
 * pages must not claim to be English: the right BCP-47 tag for romanised Hindi is
 * `hi-Latn`, and telling a search engine otherwise competes them against the
 * wrong queries. See `LIBRARY_LANG`.
 */

import fs from "node:fs";
import path from "node:path";

/** Romanised Hindi. Not "en", and not "hi" — that would imply Devanagari. */
export const LIBRARY_LANG = "hi-Latn";

/**
 * The notes live in the Python backend, which is the source of truth.
 *
 * Found by walking UP from the working directory rather than by a fixed
 * `../../`. That first version assumed `process.cwd()` was `apps/app` — true for
 * `next build` and `next dev`, and false the moment anything ran from the repo
 * root, which silently produced an empty Library. An empty Library is
 * indistinguishable from a broken path, and the broken path is a deploy that
 * shipped nothing to rank, so it is worth being robust about.
 *
 * If this app is ever deployed without the backend beside it, the search fails
 * and `allNotes` logs loudly rather than returning a quiet empty list.
 */
function findKnowledgeDir(): string {
  const relative = path.join("backend-python", "data", "knowledge");
  let dir = process.cwd();

  for (let depth = 0; depth < 6; depth += 1) {
    const candidate = path.join(dir, relative);
    if (fs.existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break; // filesystem root
    dir = parent;
  }
  // Return the most likely path anyway, so the error names something useful.
  return path.join(process.cwd(), relative);
}

const KNOWLEDGE_DIR = findKnowledgeDir();

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

const FRONT_MATTER = /^---\s*\n([\s\S]*?)\n---\s*\n/;

/**
 * Parse the `---` header.
 *
 * Deliberately not a YAML parser, matching `scripts/ingest_knowledge.py`: the
 * header only ever carries `topic` and `aliases`, these notes are hand-written,
 * and a stray colon should not take down a page. Indented continuation lines fold
 * into the previous key so a long alias list can wrap — which every note's does.
 */
function parseFrontMatter(raw: string): { fields: Record<string, string>; body: string } {
  const match = FRONT_MATTER.exec(raw);
  if (!match) return { fields: {}, body: raw };

  const fields: Record<string, string> = {};
  let key = "";
  for (const line of (match[1] ?? "").split("\n")) {
    if (!line.trim()) continue;
    if (/^\s/.test(line) && key) {
      fields[key] = `${fields[key] ?? ""} ${line.trim()}`;
    } else if (line.includes(":")) {
      const at = line.indexOf(":");
      key = line.slice(0, at).trim().toLowerCase();
      fields[key] = line.slice(at + 1).trim();
    }
  }
  return { fields, body: raw.slice(match[0].length) };
}

/** Split the body on `## ` headings, preserving order. */
function parseSections(body: string): Section[] {
  const sections: Section[] = [];
  let heading = "";
  let buffer: string[] = [];

  const flush = () => {
    const text = buffer.join("\n").trim();
    if (heading && text) sections.push({ heading, body: text });
    buffer = [];
  };

  for (const line of body.split("\n")) {
    const found = /^##\s+(.*)$/.exec(line);
    if (found) {
      flush();
      heading = (found[1] ?? "").trim();
    } else if (heading) {
      buffer.push(line);
    }
  }
  flush();
  return sections;
}

function parseNote(filename: string, raw: string): Note | null {
  const { fields, body } = parseFrontMatter(raw);
  const sections = parseSections(body);
  const slug = filename.replace(/\.md$/, "");
  const topic = fields.topic?.trim() || slug.replace(/-/g, " ");

  // A note with no sections is not publishable. Skipping beats rendering a
  // heading with nothing under it.
  if (!sections.length) return null;

  const summary =
    sections.find((s) => s.heading === "What It Is")?.body ?? sections[0]?.body ?? "";

  return {
    slug,
    filename,
    topic,
    aliases: (fields.aliases ?? "")
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean),
    sections,
    // Bullets and markdown stripped: this becomes a meta description and an
    // intro paragraph, where "- " prefixes read as broken text.
    summary: summary
      .split("\n")
      .map((l) => l.replace(/^[-*]\s*/, "").trim())
      .filter(Boolean)
      .join(" ")
      .replace(/\*\*/g, ""),
  };
}

let cached: Note[] | null = null;

/** Every publishable note, alphabetical by topic. Read once per process. */
export function allNotes(): Note[] {
  if (cached) return cached;

  let filenames: string[] = [];
  try {
    filenames = fs.readdirSync(KNOWLEDGE_DIR).filter((f) => f.endsWith(".md"));
  } catch (error) {
    // Loud, not silent. An empty Library is indistinguishable from a broken
    // path, and the second one is a deploy that shipped nothing to rank.
    console.error(`[library] could not read ${KNOWLEDGE_DIR}:`, error);
    return [];
  }

  cached = filenames
    .map((filename) => parseNote(filename, fs.readFileSync(path.join(KNOWLEDGE_DIR, filename), "utf8")))
    .filter((note): note is Note => note !== null)
    .sort((a, b) => a.topic.localeCompare(b.topic));

  return cached;
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
