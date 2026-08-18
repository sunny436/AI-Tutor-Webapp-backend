/**
 * The published knowledge base, and the guard that keeps it honest.
 *
 *   bun apps/app/src/lib/library.test.ts
 *
 * The pages now read a COMMITTED JSON file rather than the notes on disk, so that
 * the frontend can build in a repository containing no Python. That trade is only
 * safe if the JSON cannot silently fall behind the notes it was generated from —
 * the filename is the citation identifier, so a page and the note an answer cites
 * have to stay the same document.
 *
 * The last check below is what buys that: it regenerates from
 * `backend-python/data/knowledge/` and fails if the committed file differs. Drift
 * becomes a failing test and a visible diff instead of a page that disagrees with
 * the answer that cited it.
 *
 * In a repository with no notes present, that one check is skipped and reported as
 * skipped — there is nothing to compare against, and pretending otherwise would be
 * a green tick that means nothing.
 */

import { allNotes, doctorSection, metaDescription, noteBySlug } from "./library";

const results: [string, boolean, string][] = [];
const check = (name: string, ok: boolean, detail = "") => {
  results.push([name, ok, detail]);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` - ${detail}` : ""}`);
};

const notes = allNotes();

check("finds the notes at all", notes.length > 0, `${notes.length} notes`);
check("finds all 29", notes.length === 29, String(notes.length));

// Every note must be publishable, or the page renders a heading with nothing
// under it — worse than not publishing it.
const noTopic = notes.filter((n) => !n.topic.trim());
check("every note has a topic", noTopic.length === 0, noTopic.map((n) => n.slug).join(", "));

const noAliases = notes.filter((n) => n.aliases.length === 0);
check("every note has aliases", noAliases.length === 0, noAliases.map((n) => n.slug).join(", "));

const wrongSections = notes.filter((n) => n.sections.length !== 8);
check(
  "every note has all 8 sections",
  wrongSections.length === 0,
  wrongSections.map((n) => `${n.slug}:${n.sections.length}`).join(", "),
);

// The safety section is why this matters more than a content check.
const noDoctor = notes.filter((n) => !doctorSection(n));
check(
  "every note has 'When To See A Doctor'",
  noDoctor.length === 0,
  noDoctor.map((n) => n.slug).join(", "),
);

const emptySummary = notes.filter((n) => n.summary.trim().length < 20);
check(
  "every note has a usable summary for its meta description",
  emptySummary.length === 0,
  emptySummary.map((n) => n.slug).join(", "),
);

// The slug IS the citation identifier. `knowledge:acidity.md` must resolve to
// `/library/acidity`, or citation links 404 and the traceability claim breaks.
const acidity = noteBySlug("acidity");
check("a known citation resolves by slug", Boolean(acidity), acidity?.topic ?? "not found");
check("slug and filename agree", acidity?.filename === "acidity.md", acidity?.filename ?? "");
check(
  "the topic is the human name, not the filename",
  (acidity?.topic ?? "").includes("Acidity") && !(acidity?.topic ?? "").includes(".md"),
  acidity?.topic ?? "",
);

// Front matter must not leak into the rendered body.
const leaked = notes.filter((n) => n.sections.some((s) => s.body.includes("aliases:")));
check("front matter is stripped from the body", leaked.length === 0, leaked.map((n) => n.slug).join(", "));

const headingLeak = notes.filter((n) => n.sections.some((s) => s.body.startsWith("## ")));
check("section headings are not duplicated into their bodies", headingLeak.length === 0);

// Meta descriptions are a hard limit in practice; an over-long one is truncated
// by the search engine, usually mid-word.
const tooLong = notes.filter((n) => metaDescription(n).length > 156);
check(
  "meta descriptions fit",
  tooLong.length === 0,
  tooLong.map((n) => `${n.slug}:${metaDescription(n).length}`).join(", "),
);
const withBullets = notes.filter((n) => metaDescription(n).startsWith("- "));
check("meta descriptions are prose, not bullets", withBullets.length === 0);

// Hinglish is the content's actual language, and the aliases are where the
// Devanagari lives. Both matter for `lang="hi-Latn"` to be the right call.
const devanagari = notes.filter((n) => n.aliases.some((a) => /[ऀ-ॿ]/.test(a)));
check(
  "aliases carry Devanagari search terms",
  devanagari.length > 20,
  `${devanagari.length} of ${notes.length} notes`,
);

check(
  "notes are ordered for the index",
  notes.every((n, i) => i === 0 || (notes[i - 1]?.topic ?? "") <= n.topic),
);

// --- the drift guard ---------------------------------------------------------
{
  const { buildNotes } = await import("../../scripts/generate-library.mjs");
  const fs = await import("node:fs");
  const path = await import("node:path");
  const { fileURLToPath } = await import("node:url");

  let dir: string | null = null;
  let probe = process.cwd();
  for (let i = 0; i < 6; i += 1) {
    const candidate = path.join(probe, "backend-python", "data", "knowledge");
    if (fs.existsSync(candidate)) { dir = candidate; break; }
    const parent = path.dirname(probe);
    if (parent === probe) break;
    probe = parent;
  }

  if (!dir) {
    console.log("SKIP  committed JSON matches the notes - no notes in this repository");
  } else {
    const rebuilt = JSON.stringify(buildNotes(dir), null, 2) + "\n";
    // Resolved from THIS MODULE, never process.cwd(): the suite is run both from
    // the repo root and from apps/app, and a cwd-relative path silently reads a
    // file that does not exist — which reports as "stale" rather than as a broken
    // test path. That exact mistake is why library.ts walks up instead of guessing.
    const committedPath = fileURLToPath(new URL("../content/library.json", import.meta.url));
    const committed = fs.existsSync(committedPath)
      ? fs.readFileSync(committedPath, "utf8")
      : "";
    check(
      "committed library.json still matches the notes on disk",
      rebuilt === committed,
      rebuilt === committed ? "" : "stale - run: bun run library:generate",
    );
  }
}

const passed = results.filter(([, ok]) => ok).length;
console.log(`\n===== library: ${passed}/${results.length} passed =====`);
if (passed !== results.length) {
  console.log("\nFailing:");
  for (const [name, ok, detail] of results) if (!ok) console.log(`  - ${name}: ${detail}`);
}
process.exit(passed === results.length ? 0 : 1);
