import { Leaf, Search } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { LIBRARY_LANG, allNotes } from "@/lib/library";
import { canonical, siteUrl } from "@/lib/seo";

/**
 * The knowledge base, published.
 *
 * These 29 notes have always been in the product — they are what every answer is
 * retrieved from and cited against — but they existed only as retrieval fodder.
 * Nothing outside a consultation could read them, and nothing could index them.
 * That is the largest ranking opportunity here, and it is content that already
 * exists and is already trusted enough to cite.
 *
 * Read straight from `backend-python/data/knowledge/`, never copied: the
 * filename is the citation identifier, so the page and the cited note must stay
 * the same document. See `lib/library.ts`.
 */

export const metadata: Metadata = {
  title: "Ayurveda Knowledge Library",
  description:
    "Ayurveda aur Yoga guidance for everyday health problems — acidity, gas, neend, baal jhadna aur bahut kuch. Har topic par root cause, khaana, yoga aur daily routine.",
  alternates: { canonical: canonical("/library") },
};

export default function LibraryIndex() {
  const notes = allNotes();

  return (
    <div className="relative min-h-dvh bg-background">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />

      <main id="main" className="relative mx-auto max-w-5xl px-4 py-14 sm:px-6 sm:py-20">
        <header className="max-w-2xl">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-sm text-text-secondary transition-colors hover:text-foreground"
          >
            <span
              aria-hidden
              className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-brand-foreground"
            >
              <Leaf className="h-4 w-4" />
            </span>
            Ayurveda
          </Link>

          <h1 className="mt-6 font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            The knowledge library
          </h1>
          {/* Says plainly what these are and where answers come from. This is the
              product's actual claim, so it belongs above the fold rather than in
              a footer nobody reads. */}
          <p className="mt-4 text-base leading-relaxed text-text-secondary">
            Every plan this assistant writes is drawn from these {notes.length} notes, and
            says which ones it used. They are published here in full so you can read the
            source yourself.
          </p>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            Educational wellness guidance only — not a diagnosis, and not a substitute for
            your doctor.
          </p>
        </header>

        {notes.length === 0 ? (
          <p className="mt-12 rounded-xl border border-border bg-card p-6 text-sm text-text-secondary">
            The library could not be loaded.
          </p>
        ) : (
          <ul className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {notes.map((note) => (
              <li key={note.slug}>
                <Link
                  href={`/library/${note.slug}`}
                  className="flex h-full flex-col rounded-2xl border border-border bg-card p-5 elev-1 transition-colors hover:border-brand/40"
                >
                  {/* The topic is English; the body it summarises is Hinglish.
                      Tagging the summary keeps a screen reader from reading
                      romanised Hindi with an English voice. */}
                  <span className="font-display text-base font-semibold text-foreground">
                    {note.topic}
                  </span>
                  <span
                    lang={LIBRARY_LANG}
                    className="mt-2 line-clamp-3 text-sm leading-relaxed text-text-secondary"
                  >
                    {note.summary}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}

        <section className="mt-14 rounded-2xl border border-border bg-surface p-6">
          <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-foreground">
            <Search aria-hidden className="h-4 w-4 text-accent-warm" />
            Looking for something specific?
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">
            Ask in your own words — English, Hindi or Hinglish — and the assistant will
            find the right notes and build a plan from them.
          </p>
          <Link
            href="/consult"
            className="mt-4 inline-flex items-center rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground transition-opacity hover:opacity-90"
          >
            Start a consultation
          </Link>
        </section>
      </main>

      {/* CollectionPage + ItemList: tells a crawler these are one coherent set
          rather than 29 unrelated pages that happen to share a path. */}
      <script
        type="application/ld+json"
        // biome-ignore lint/security/noDangerouslySetInnerHtml: JSON-LD, built from our own data
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            name: "Ayurveda Knowledge Library",
            url: `${siteUrl()}/library`,
            inLanguage: LIBRARY_LANG,
            mainEntity: {
              "@type": "ItemList",
              numberOfItems: notes.length,
              itemListElement: notes.map((note, index) => ({
                "@type": "ListItem",
                position: index + 1,
                name: note.topic,
                url: `${siteUrl()}/library/${note.slug}`,
              })),
            },
          }),
        }}
      />
    </div>
  );
}
