/**
 * The published knowledge base, checked against the real notes.
 *
 *   bun apps/app/src/lib/library.test.ts
 *
 * Reads `backend-python/data/knowledge/` — the same files the retriever searches
 * and cites. That is the point: if this suite passes but the pages are empty,
 * the path is wrong, and an empty Library is indistinguishable from a deploy
 * that shipped nothing to rank.
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

const passed = results.filter(([, ok]) => ok).length;
console.log(`\n===== library: ${passed}/${results.length} passed =====`);
if (passed !== results.length) {
  console.log("\nFailing:");
  for (const [name, ok, detail] of results) if (!ok) console.log(`  - ${name}: ${detail}`);
}
process.exit(passed === results.length ? 0 : 1);
