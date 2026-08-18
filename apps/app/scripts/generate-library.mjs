/**
 * Turn the curated notes into `src/content/library.json`.
 *
 * WHY THIS EXISTS
 * The Library pages used to read `backend-python/data/knowledge/*.md` straight off
 * disk at build time. That kept one source of truth — the filename IS the citation
 * identifier, so the page at /library/acidity and the note the assistant cites had
 * to be the same document — but it also meant the frontend could not build without
 * the Python backend sitting beside it. With the frontend moving to its own
 * repository, that is no longer a workable assumption.
 *
 * So the notes are compiled to JSON here, and the JSON is COMMITTED. The frontend
 * imports it as a module: no `fs`, no path walking, nothing outside its own tree.
 *
 * THE GUARANTEE IS KEPT, NOT TRADED AWAY
 * This runs in the repository that owns the notes, and `library.test.ts` fails if
 * the committed JSON no longer matches them. A stale file is therefore a failing
 * test and a visible diff, rather than a page quietly disagreeing with the answer
 * that cited it.
 *
 *     bun run library:generate
 *
 * In the frontend-only repository there are no notes to read. That is expected:
 * this exits successfully and leaves the committed JSON alone, so `prebuild` is
 * safe to run in both places.
 */

import fs from "node:fs";
import path from "node:path";

const OUT = path.join(process.cwd(), "src", "content", "library.json");

/** Walk up looking for the notes, so this works from any working directory. */
function findKnowledgeDir() {
  const relative = path.join("backend-python", "data", "knowledge");
  let dir = process.cwd();
  for (let depth = 0; depth < 6; depth += 1) {
    const candidate = path.join(dir, relative);
    if (fs.existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

const FRONT_MATTER = /^---\s*\n([\s\S]*?)\n---\s*\n/;

/**
 * Parse the `---` header.
 *
 * Deliberately not a YAML parser, matching `scripts/ingest_knowledge.py`: the
 * header only ever carries `topic` and `aliases`, these notes are hand-written,
 * and a stray colon should not take down a page. Indented continuation lines fold
 * into the previous key so a long alias list can wrap — which every note's does.
 */
function parseFrontMatter(raw) {
  const match = FRONT_MATTER.exec(raw);
  if (!match) return { fields: {}, body: raw };

  const fields = {};
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
function parseSections(body) {
  const sections = [];
  let heading = "";
  let buffer = [];

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

function parseNote(filename, raw) {
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
    // Bullets and markdown stripped: this becomes a meta description and an intro
    // paragraph, where "- " prefixes read as broken text.
    summary: summary
      .split("\n")
      .map((l) => l.replace(/^[-*]\s*/, "").trim())
      .filter(Boolean)
      .join(" ")
      .replace(/\*\*/g, ""),
  };
}

export function buildNotes(dir) {
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".md"))
    .map((filename) => parseNote(filename, fs.readFileSync(path.join(dir, filename), "utf8")))
    .filter((note) => note !== null)
    .sort((a, b) => a.topic.localeCompare(b.topic));
}

function main() {
  const dir = findKnowledgeDir();
  if (!dir) {
    // The frontend-only repository. Expected, and not an error.
    console.log("[library] no knowledge directory found - keeping the committed JSON");
    return;
  }

  const notes = buildNotes(dir);
  if (!notes.length) {
    // Found the directory but parsed nothing. That IS an error: overwriting a good
    // file with an empty one would ship a Library with no content.
    console.error(`[library] ${dir} produced no notes - refusing to overwrite ${OUT}`);
    process.exit(1);
  }

  const next = `${JSON.stringify(notes, null, 2)}\n`;
  const current = fs.existsSync(OUT) ? fs.readFileSync(OUT, "utf8") : "";
  if (current === next) {
    console.log(`[library] ${notes.length} notes - already up to date`);
    return;
  }

  fs.writeFileSync(OUT, next, "utf8");
  console.log(`[library] wrote ${notes.length} notes to ${path.relative(process.cwd(), OUT)}`);
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith("generate-library.mjs")) {
  main();
}
