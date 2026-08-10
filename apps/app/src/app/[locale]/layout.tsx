import "@v1/ui/globals.css";
import { ConvexAuthNextjsServerProvider } from "@convex-dev/auth/nextjs/server";
import { TooltipProvider } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import { ConvexClientProvider } from "../convex-client-provider";

export const metadata: Metadata = {
  title: "Create v1",
  description: "Production ready Next.js app",
};

export const viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)" },
    { media: "(prefers-color-scheme: dark)" },
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
            `${GeistSans.variable} ${GeistMono.variable}`,
            "antialiased",
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
