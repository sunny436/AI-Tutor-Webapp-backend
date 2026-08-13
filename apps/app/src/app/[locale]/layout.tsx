import "@v1/ui/globals.css";
import { ConvexAuthNextjsServerProvider } from "@convex-dev/auth/nextjs/server";
import { TooltipProvider } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";
import { Fraunces } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { ConvexClientProvider } from "../convex-client-provider";

/**
 * The display face. Self-hosted at build time by `next/font/google` — no request
 * ever leaves the user's browser for it, which is why this is safe under the
 * app's own security headers and costs no third-party connection.
 *
 * A reading serif rather than another geometric sans. This product's job is to
 * present sourced health guidance, so its headings should look like a reference
 * work; Inter and Space Grotesk are avoided deliberately, being the two faces
 * that make a page read as generated rather than designed.
 */
const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
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
    default: "Ayurveda — AI wellness guidance, traced to its sources",
    template: "%s · Ayurveda",
  },
  description:
    "Describe what is troubling you in English, Hindi or Hinglish. Get a personalised Ayurveda and Yoga plan — root cause, food chart, yoga, daily routine — drawn from a curated knowledge base, with its sources shown.",
  applicationName: "Ayurveda",
  openGraph: {
    type: "website",
    siteName: "Ayurveda",
    title: "Ayurveda — AI wellness guidance, traced to its sources",
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
    { media: "(prefers-color-scheme: light)", color: "#FBFAF7" },
    { media: "(prefers-color-scheme: dark)", color: "#0E1614" },
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
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ConvexAuthNextjsServerProvider>
      <html lang="en" suppressHydrationWarning>
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
            `${GeistSans.variable} ${GeistMono.variable} ${display.variable}`,
            // `font-sans` is not redundant. The `.variable` classes only DEFINE
            // the custom properties; without a font utility actually consuming
            // them, every one of these faces is downloaded and then ignored —
            // which is exactly what was happening before.
            "font-sans antialiased",
          )}
        >
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
