"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { stripLocale } from "@/lib/locales";
import { NotificationsBell } from "./notifications-bell";

const APP_VERSION = "0.1.0";

// Keyed by the LOCALE-STRIPPED path. Keyed by the raw pathname it never matched
// once, because the URL is always `/en/...` — so this breadcrumb read
// "Dashboard" on every page of the app, chat included. See lib/locales.ts.
const TITLES: Record<string, string> = {
  "/": "Home",
  "/consult": "Consultation",
  "/jobs": "Jobs",
  "/platform": "Platform",
  "/files": "Reports",
  "/settings": "Settings",
  "/settings/billing": "Billing",
};

export function Topbar() {
  const path = stripLocale(usePathname());
  const title = TITLES[path];

  return (
    // h-14, matching the sidebar header and the sidebar's mobile bar. At h-12
    // the two horizontal rules meeting at the sidebar edge were 8px apart.
    // NOTE: consult/page.tsx subtracts this height twice — see the comment there.
    //
    // No `bg-card`: the sidebar is `bg-surface` and card is LIGHTER than both,
    // so the topbar read as the brightest thing on screen. Transparent lets
    // PageShell's backdrop-wash run continuously from the top of the viewport.
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4 sm:px-6">
      {/* A breadcrumb whose first crumb is not a link is just decoration. */}
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-sm">
        <Link
          href="/"
          className="focus-ring shrink-0 rounded-md text-text-secondary transition-colors hover:text-foreground"
        >
          Ayurveda
        </Link>
        {title && path !== "/" && (
          <>
            <span aria-hidden className="text-border">
              /
            </span>
            <span aria-current="page" className="truncate font-medium text-foreground">
              {title}
            </span>
          </>
        )}
      </nav>
      <div className="flex items-center gap-2 text-xs text-text-secondary">
        <NotificationsBell />
        {/* The Help link pointed at github.com/get-convex/v1 — the starter
            template's own documentation, which says nothing about this product.
            Removed rather than repointed: there is no docs site to send anyone
            to yet, and a link to someone else's README is worse than none. */}
        <span className="hidden font-mono text-2xs text-text-secondary sm:inline">
          v{APP_VERSION}
        </span>
      </div>
    </header>
  );
}
