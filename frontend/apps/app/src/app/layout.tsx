import "@v1/ui/globals.css";
import { TooltipProvider } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import type { Metadata, Viewport } from "next";
import { Eczar, Hanken_Grotesk } from "next/font/google";
import { ThemeProvider } from "next-themes";
import type { CSSProperties, ReactNode } from "react";
import { Toaster } from "sonner";

import { APP_NAME, BRAND } from "@/lib/brand";
import { siteUrl } from "@/lib/site";

// Self-hosted at build time by next/font: no request leaves the browser for them.
const display = Eczar({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--font-display", display: "swap" });
const ui = Hanken_Grotesk({ subsets: ["latin"], variable: "--font-ui", display: "swap" });

// Code is read a lot in a chatbot: the system monospace face (no download) reads
// better at length than a wide display mono.
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
    { media: "(prefers-color-scheme: light)", color: "#F3F0E7" },
    { media: "(prefers-color-scheme: dark)", color: "#171512" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={cn(ui.variable, display.variable, "font-sans antialiased")} style={fonts}>
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
