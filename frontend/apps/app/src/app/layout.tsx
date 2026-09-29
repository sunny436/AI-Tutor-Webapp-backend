import "@v1/ui/globals.css";
import { TooltipProvider } from "@v1/ui/tooltip";
import type { Metadata, Viewport } from "next";
import { ThemeProvider } from "next-themes";
import type { CSSProperties, ReactNode } from "react";
import { Toaster } from "sonner";

import { PREPAINT_SCRIPT } from "@/lib/appearance";
import { notoSans, notoSansDevanagari } from "@/lib/fonts";
import { APP_NAME, BRAND } from "@/lib/brand";
import { siteUrl } from "@/lib/site";

// Every face is the platform's own (tailwind.config.ts in packages/ui): nothing
// to download. Code is read a lot in a tutor's answers, and the system monospace
// face reads better at length than a wide display mono.
const fonts = {
  "--font-mono": 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
} as CSSProperties;

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: BRAND.description,
  applicationName: APP_NAME,
  // The one brand asset (lib/brand.ts), so the tab icon changes with the logo.
  icons: { icon: { url: BRAND.markSrc, type: "image/svg+xml" } },
  // A private app: nothing here is for search engines.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F7F8FA" },
    { media: "(prefers-color-scheme: dark)", color: "#0F1117" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${notoSans.variable} ${notoSansDevanagari.variable}`} suppressHydrationWarning>
      <head>
        {/* Text size, contrast, motion and reading spacing from the last visit, before the
            first paint (lib/appearance.ts); the signed-in app then applies the server's value. */}
        {/* biome-ignore lint/security/noDangerouslySetInnerHtml: a constant script, no user data */}
        <script dangerouslySetInnerHTML={{ __html: PREPAINT_SCRIPT }} />
      </head>
      <body className="font-sans antialiased" style={fonts}>
        {/* WCAG 2.4.1: every page's main region carries id="main". */}
        <a
          href="#main"
          className="sr-only z-50 focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:rounded-xl focus:bg-brand focus:px-4 focus:py-2.5 focus:text-sm focus:font-medium focus:text-brand-foreground focus:outline-none focus:ring-2 focus:ring-brand/40"
        >
          Skip to content
        </a>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
          <Toaster richColors position="top-center" />
        </ThemeProvider>
      </body>
    </html>
  );
}
