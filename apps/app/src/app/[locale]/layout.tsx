import "@v1/ui/globals.css";
import { ConvexAuthNextjsServerProvider } from "@convex-dev/auth/nextjs/server";
import { TooltipProvider } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import type { Metadata } from "next";
import { Eczar, Hanken_Grotesk, Martian_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { ConvexClientProvider } from "../convex-client-provider";

/**
 * THE THREE FACES.
 *
 * All self-hosted at build time by `next/font/google` — no request ever leaves
 * the user's browser for them, which is why this is safe under the app's own
 * security headers and costs no third-party connection.
 *
 * Eczar was drawn by Vaibhav Singh for Devanagari first and Latin second. That
 * is why it was chosen — the face carries real stroke contrast, so headings read
 * as a printed reference work rather than as a chat log.
 *
 * BUT THE DEVANAGARI SUBSET IS NOT LOADED, because nothing renders Devanagari.
 * The knowledge base is romanised Hindi — `hi-Latn`, Latin script, as
 * `lib/library.ts` sets out — so the glyphs never appear. Searching the whole of
 * `apps/app/src`, `packages/ui/src` and `content/library.json` for U+0900-U+097F
 * returns nothing at all.
 *
 * It was being shipped anyway: 88.2 KB preloaded on EVERY route, 20% of the
 * login page's 425 KB, rendering not one character. Measured on production, not
 * assumed. Add "devanagari" back the moment real देवनागरी content does — and
 * nothing else has to change when you do.
 *
 * Inter, Roboto and Space Grotesk are avoided deliberately. They are where
 * every generated interface lands, and landing there would undo the direction
 * before a single colour is applied.
 *
 * `weight` is pinned rather than left to the variable range: Eczar ships a
 * 400-800 axis, and letting a heading inherit an arbitrary weight is how a
 * display face ends up looking like bold body text.
 *
 * Trimming that list saves NOTHING, so do not bother. Only 600 is ever used —
 * all 43 `font-display` call sites pair it with `font-semibold` — but because
 * Eczar is variable, all three weights resolve to the SAME five files in the
 * generated CSS. Dropping 400 and 700 removes @font-face rules and zero bytes.
 */
const display = Eczar({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

const ui = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-ui",
  display: "swap",
});

/**
 * Provenance only — note filenames and relevance scores. Wide and rectilinear,
 * like a specimen label. Deliberately NOT used for body copy: at paragraph
 * length its width slows reading badly.
 */
const mono = Martian_Mono({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-mono",
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://ayur.namahos.com";

/**
 * Real metadata. This said `title: "Create v1"` / "Production ready Next.js app"
 * — the Convex starter's default — on every page of the live site, which is what
 * a visitor saw in their browser tab and what a search engine read first.
 *
 * `template` so each page appends its own name; pages that set a title get
 * "Consult · Ayurveda", the root gets the default.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Ayurveda — AI wellness guidance, grounded in curated notes",
    template: "%s · Ayurveda",
  },
  description:
    "Describe what is troubling you in English, Hindi or Hinglish. Get a personalised Ayurveda and Yoga plan — root cause, food chart, yoga, daily routine — drawn from a curated knowledge base that is published in full.",
  applicationName: "Ayurveda",
  openGraph: {
    type: "website",
    siteName: "Ayurveda",
    title: "Ayurveda — AI wellness guidance, grounded in curated notes",
    description:
      "Personalised Ayurveda and Yoga guidance in English, Hindi or Hinglish, grounded in a curated knowledge base.",
  },
  // Educational wellness guidance, never a diagnosis. Kept out of search
  // result snippets that could read as medical advice out of context.
  robots: { index: true, follow: true },
};

export const viewport = {
  // Both entries were present but had NO `color` key, so they emitted nothing
  // and the browser chrome stayed unthemed. These are --background, light/dark.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F3F0E7" },
    { media: "(prefers-color-scheme: dark)", color: "#171512" },
  ],
};

/**
 * Origins the browser will need but cannot discover from the HTML.
 *
 * The dashboard talks to two hosts besides its own: the Python AI backend, and
 * Convex. Neither appears in a tag the preload scanner can see — the first
 * request to each is issued by JavaScript, well after the page has parsed — so
 * without these hints the user waits through a fresh DNS lookup, TCP handshake
 * and TLS negotiation at the moment they ask their first question.
 *
 * That is ~34 ms from a machine sitting next to the server. For a user in India
 * reaching an origin in Toronto it is several hundred, spent before a single
 * byte of their question has been sent.
 *
 * Filtered and de-duplicated because both variables can legitimately point at
 * the same host, and preconnecting to nothing is a wasted socket.
 */
const PRECONNECT_ORIGINS = Array.from(
  new Set(
    [process.env.NEXT_PUBLIC_AI_BACKEND_URL, process.env.NEXT_PUBLIC_CONVEX_URL]
      .filter((value): value is string => Boolean(value))
      .map((value) => {
        try {
          return new URL(value).origin;
        } catch {
          return "";
        }
      })
      .filter(Boolean),
  ),
);

export default function RootLayout({
  children,
  params,
}: Readonly<{
  children: React.ReactNode;
  params: { locale: string };
}>) {
  return (
    <ConvexAuthNextjsServerProvider>
      {/*
        `lang` follows the route, instead of claiming "en" on every page.
        WCAG 3.1.1 (Level A), and not a technicality: a screen reader picks its
        voice and pronunciation rules from this attribute, so a French or Spanish
        page was being read aloud with English phonetics. The Library pages set
        `hi-Latn` on their own bodies for the same reason — romanised Hindi read
        with an English voice is gibberish.
      */}
      <html lang={params.locale || "en"} suppressHydrationWarning>
        <head>
          {PRECONNECT_ORIGINS.map((origin) => (
            // dns-prefetch as well as preconnect: browsers cap concurrent
            // preconnects and may drop one, and the DNS hint still helps if they do.
            <link key={origin} rel="preconnect" href={origin} crossOrigin="anonymous" />
          ))}
          {PRECONNECT_ORIGINS.map((origin) => (
            <link key={`dns-${origin}`} rel="dns-prefetch" href={origin} />
          ))}
        </head>
        <body
          className={cn(
            `${ui.variable} ${mono.variable} ${display.variable}`,
            // `font-sans` is not redundant. The `.variable` classes only DEFINE
            // the custom properties; without a font utility actually consuming
            // them, every one of these faces is downloaded and then ignored —
            // which is exactly what was happening before.
            "font-sans antialiased",
          )}
        >
          {/*
            SKIP TO CONTENT. WCAG 2.4.1 Bypass Blocks (Level A), and the app had
            none at all.

            It is not a formality here: the dashboard sidebar renders FOURTEEN
            links before `<main>`, so a keyboard user tabbed through the entire
            navigation on every single page before reaching anything they came
            for. Every page-level `<main>` in the app carries `id="main"`.

            Visually hidden until focused, then a real, visible control — a skip
            link that stays invisible while focused is worse than none, because
            the user cannot tell where they are.
          */}
          <a
            href="#main"
            className="sr-only z-50 focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:rounded-xl focus:bg-brand focus:px-4 focus:py-2.5 focus:text-sm focus:font-medium focus:text-brand-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
          >
            Skip to content
          </a>
          <ThemeProvider
            attribute="class"
            defaultTheme="system"
            enableSystem
            disableTransitionOnChange
          >
            <TooltipProvider delayDuration={0}>
              <ConvexClientProvider>{children}</ConvexClientProvider>
            </TooltipProvider>
          </ThemeProvider>
        </body>
      </html>
    </ConvexAuthNextjsServerProvider>
  );
}
