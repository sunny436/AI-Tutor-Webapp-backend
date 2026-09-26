"use client";

import { cn } from "@v1/ui/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { SETTINGS_SECTIONS } from "./sections";

/**
 * Settings: the list of sections beside the open one. Every section has its own address
 * (`/settings/<section>`), so it can be linked to and survives a reload.
 *
 * On a wide screen the list is a column; on a phone it is a row of links that scrolls
 * sideways inside itself (never the page). Plain links, not a <select> that navigates as the
 * arrow keys move through it.
 */
export function SettingsFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6 md:flex-row md:gap-10 md:py-8">
        <nav aria-label="Settings sections" className="min-w-0 md:w-60 md:shrink-0">
          <ul className="scrollbar-subtle -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 md:sticky md:top-0 md:flex-col md:overflow-visible md:pb-0">
            {SETTINGS_SECTIONS.map((section) => {
              const href = `/settings/${section.slug}`;
              const current = pathname === href;
              const Icon = section.icon;
              return (
                <li key={section.slug} className="shrink-0">
                  <Link
                    href={href}
                    aria-current={current ? "page" : undefined}
                    className={cn(
                      "focus-ring flex items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                      current
                        ? "bg-brand-soft text-brand"
                        : "text-text-secondary hover:bg-surface-2 hover:text-foreground",
                    )}
                  >
                    <Icon aria-hidden className="h-4 w-4 shrink-0" />
                    {section.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
