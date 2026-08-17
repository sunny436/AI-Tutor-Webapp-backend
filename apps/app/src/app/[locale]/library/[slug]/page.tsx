import { AlertTriangle, ArrowLeft, Leaf } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  LIBRARY_LANG,
  allNotes,
  doctorSection,
  metaDescription,
  noteBySlug,
} from "@/lib/library";
import { canonical, siteUrl } from "@/lib/seo";

/**
 * One published note.
 *
 * The page a citation points at. `answer-sources.tsx` renders
 * `knowledge:acidity.md` under every answer, and those chips now link here — so
 * a reader can check any claim in one click, and every consultation quietly
 * builds internal links into the content that ranks.
 *
 * THE SAFETY SECTION IS PINNED, NOT LISTED IN ORDER.
 * `ALWAYS_INCLUDED` in `consult/sections.py` forces "When To See A Doctor" into
 * every generated plan. The same reasoning applies harder to a page someone
 * lands on cold from a search: these notes tell people that blood in vomit,
 * black stools or chest pain radiating to the jaw need a doctor rather than a
 * diet change, and that must not sit eighth on the page.
 */

export function generateStaticParams() {
  return allNotes().map((note) => ({ slug: note.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: { slug: string };
}): Promise<Metadata> {
  const note = noteBySlug(params.slug);
  if (!note) return {};

  const url = canonical(`/library/${note.slug}`);
  return {
    title: note.topic,
    description: metaDescription(note),
    alternates: { canonical: url },
    openGraph: {
      title: note.topic,
      description: metaDescription(note),
      url,
      type: "article",
    },
  };
}

export default function NotePage({ params }: { params: { slug: string } }) {
  const note = noteBySlug(params.slug);
  if (!note) notFound();

  const doctor = doctorSection(note);
  const body = note.sections.filter((s) => s.heading !== "When To See A Doctor");

  return (
    <div className="relative min-h-dvh bg-background">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />

      <main id="main" className="relative mx-auto max-w-3xl px-4 py-14 sm:px-6 sm:py-20">
        <nav className="flex items-center gap-4 text-sm">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-text-secondary transition-colors hover:text-foreground"
          >
            <span
              aria-hidden
              className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-brand-foreground"
            >
              <Leaf className="h-4 w-4" />
            </span>
            Ayurveda
          </Link>
          <Link
            href="/library"
            className="inline-flex items-center gap-1.5 text-text-secondary transition-colors hover:text-foreground"
          >
            <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
            Library
          </Link>
        </nav>

        <article className="mt-8">
          <h1 className="font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            {note.topic}
          </h1>

          {/* The aliases the author wrote by hand, shown as what they are.
              Real value to a reader who arrived searching one of these terms —
              and it puts the Hinglish and Devanagari phrasings in the BODY,
              where they belong. Not meta-keywords: search engines stopped
              reading those two decades ago. */}
          {note.aliases.length > 0 && (
            <p className="mt-3 text-sm leading-relaxed text-text-secondary">
              <span className="font-medium text-foreground">Also known as: </span>
              <span lang={LIBRARY_LANG}>{note.aliases.join(" · ")}</span>
            </p>
          )}

          {/* Pinned, above the content. Never collapsed. */}
          {doctor && (
            <aside
              // Not `role="alert"`: this is standing safety information, not an
              // event. An alert role would interrupt a screen reader on page load
              // and then never fire again, which is the wrong shape for both.
              aria-labelledby="see-a-doctor"
              className="mt-8 rounded-2xl border border-destructive/30 bg-destructive/5 p-5"
            >
              <h2
                id="see-a-doctor"
                className="flex items-center gap-2 font-display text-base font-semibold text-destructive"
              >
                <AlertTriangle aria-hidden className="h-4 w-4 shrink-0" />
                When to see a doctor
              </h2>
              <div lang={LIBRARY_LANG} className="mt-3">
                <Prose text={doctor.body} />
              </div>
            </aside>
          )}

          <div lang={LIBRARY_LANG} className="mt-10 space-y-10">
            {body.map((section) => (
              <section key={section.heading}>
                <h2 lang="en" className="font-display text-xl font-semibold text-foreground">
                  {section.heading}
                </h2>
                <div className="mt-3">
                  <Prose text={section.body} />
                </div>
              </section>
            ))}
          </div>

          <footer className="mt-14 border-t border-border pt-6">
            {/* The byline slot. Intentionally NOT filled with an invented name or
                qualification: health content is held to an expertise bar met by a
                real, named, credentialed reviewer, and fabricating one would be a
                false claim about medical oversight. The markup is here and ready. */}
            <p className="text-sm text-text-secondary">
              Educational Ayurveda and Yoga guidance. This is not a diagnosis, not a
              prescription, and not a substitute for your doctor. It never names a
              medicine or a dose.
            </p>
            <p className="mt-4 text-2xs text-text-secondary">
              Source: <code className="font-mono">{note.filename}</code> — the same note
              the assistant cites when it uses this material.
            </p>
          </footer>
        </article>

        <div className="mt-12 rounded-2xl border border-border bg-surface p-6">
          <h2 className="font-display text-lg font-semibold text-foreground">
            Want this as a plan for you?
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">
            Describe what you are feeling in your own words and the assistant will build
            one from these notes.
          </p>
          <Link
            href="/consult"
            className="mt-4 inline-flex items-center rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground transition-opacity hover:opacity-90"
          >
            Start a consultation
          </Link>
        </div>
      </main>

      <script
        type="application/ld+json"
        // biome-ignore lint/security/noDangerouslySetInnerHtml: JSON-LD, built from our own data
        dangerouslySetInnerHTML={{
          __html: JSON.stringify([
            {
              "@context": "https://schema.org",
              "@type": "MedicalWebPage",
              name: note.topic,
              url: `${siteUrl()}/library/${note.slug}`,
              description: metaDescription(note),
              inLanguage: LIBRARY_LANG,
              // No `reviewedBy`, and that is deliberate: it must name a real,
              // credentialed person. An invented one would be a fabricated claim
              // of medical review.
            },
            {
              "@context": "https://schema.org",
              "@type": "BreadcrumbList",
              itemListElement: [
                { "@type": "ListItem", position: 1, name: "Library", item: `${siteUrl()}/library` },
                { "@type": "ListItem", position: 2, name: note.topic },
              ],
            },
          ]),
        }}
      />
    </div>
  );
}

/**
 * The notes' markdown, which is only ever `- bullets` and plain paragraphs.
 *
 * A full markdown renderer would be a dependency and an XSS surface for content
 * that uses two constructs. `**bold**` is stripped rather than rendered: it
 * appears mid-sentence in these notes as emphasis, and dropping it reads better
 * than a bold fragment in the middle of a line.
 */
function Prose({ text }: { text: string }) {
  const blocks: Array<{ type: "ul" | "p"; lines: string[] }> = [];

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    const last = blocks[blocks.length - 1];

    if (bullet) {
      const item = bullet[1] ?? "";
      if (last?.type === "ul") last.lines.push(item);
      else blocks.push({ type: "ul", lines: [item] });
    } else if (last?.type === "p") {
      last.lines.push(line);
    } else {
      blocks.push({ type: "p", lines: [line] });
    }
  }

  const clean = (s: string) => s.replace(/\*\*/g, "");

  return (
    <>
      {blocks.map((block, index) =>
        block.type === "ul" ? (
          <ul
            // biome-ignore lint/suspicious/noArrayIndexKey: static content, never reordered
            key={index}
            className="ml-1 space-y-2 text-sm leading-relaxed text-text-secondary"
          >
            {block.lines.map((line) => (
              <li key={line} className="flex gap-2.5">
                <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-warm" />
                <span>{clean(line)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p
            // biome-ignore lint/suspicious/noArrayIndexKey: static content, never reordered
            key={index}
            className="text-sm leading-relaxed text-text-secondary"
          >
            {clean(block.lines.join(" "))}
          </p>
        ),
      )}
    </>
  );
}
