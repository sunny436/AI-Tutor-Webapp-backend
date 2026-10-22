"use client";

import { cn } from "@v1/ui/utils";
import { ChevronRight, LogOut, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";

import { BrandLockup } from "@/components/brand/brand-mark";
import { useSignOut } from "@/components/use-sign-out";
import { UserAvatar } from "@/components/user-avatar";
import { useUser } from "@/components/user-context";
import { matchSections } from "./sections";
import { CloseSettings, useWorkspace } from "./workspace-context";

const ANNOUNCE_AFTER_MS = 300;

/**
 * What the Settings panel holds: the brand and Close (desktop; the phone's are in its top bar),
 * search, the sections and the account. `panel` is the desktop column beside the open section;
 * `list` is the phone's `/settings` screen, where each row also says what the section holds.
 */
export function SettingsPanel({ variant }: { variant: "panel" | "list" }) {
  const pathname = usePathname();
  const { closeHref, openSection } = useWorkspace();
  const { user } = useUser();
  const { signOut, signingOut } = useSignOut();
  const [query, setQuery] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const results = useMemo(() => matchSections(query), [query]);
  const list = useRef<HTMLUListElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const ids = useId();
  const searchId = `${ids}-search`;
  const listId = `${ids}-sections`;
  const name = user.displayName || user.email;

  // Typed before the page finished loading (a slow phone): the box shows it, so search it.
  useEffect(() => {
    const early = input.current?.value;
    if (early) setQuery(early);
  }, []);

  // One announcement once typing pauses, not one per keystroke.
  useEffect(() => {
    const words = query.trim();
    if (!words) {
      setAnnouncement("");
      return;
    }
    const count = results.length;
    const timer = window.setTimeout(
      () =>
        setAnnouncement(
          count ? `${count} ${count === 1 ? "category" : "categories"} match` : `No settings match “${words}”`,
        ),
      ANNOUNCE_AFTER_MS,
    );
    return () => window.clearTimeout(timer);
  }, [query, results.length]);

  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const first = results[0];
      if (first && openSection(first.slug)) setQuery("");
    } else if (event.key === "ArrowDown") {
      const first = list.current?.querySelector<HTMLElement>("a");
      if (first) {
        event.preventDefault();
        first.focus();
      }
    } else if (event.key === "Escape" && query) {
      event.preventDefault();
      setQuery("");
    }
  };

  return (
    <div className={cn("flex min-h-0 flex-col", variant === "panel" ? "h-full" : "gap-1")}>
      {variant === "panel" && (
        <div className="flex shrink-0 items-center justify-between gap-3 px-4 pb-4 pt-5">
          <BrandLockup compact />
          <CloseSettings href={closeHref} />
        </div>
      )}

      <div className={cn("shrink-0", variant === "panel" ? "px-4 pb-3" : "pb-3")}>
        <label htmlFor={searchId} className="sr-only">
          Search settings
        </label>
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-secondary"
          />
          <input
            ref={input}
            id={searchId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onSearchKey}
            placeholder="Search settings"
            autoComplete="off"
            aria-controls={listId}
            className="focus-field h-11 w-full rounded-xl border border-input bg-card pl-9 pr-3 text-base text-foreground placeholder:text-text-secondary sm:text-sm md:h-10"
          />
        </div>
        <p role="status" className="sr-only">
          {announcement}
        </p>
      </div>

      <nav
        aria-label="Settings sections"
        className={cn("min-h-0", variant === "panel" && "scrollbar-subtle flex-1 overflow-y-auto overscroll-contain px-3 pb-3")}
      >
        {results.length === 0 ? (
          <p className="px-3 py-4 text-sm text-text-secondary">No settings match “{query.trim()}”.</p>
        ) : (
          <ul id={listId} ref={list} className={cn("flex flex-col", variant === "panel" ? "gap-1" : "gap-2")}>
            {results.map((section) => {
              const href = `/settings/${section.slug}`;
              const current = pathname === href;
              const Icon = section.icon;
              return (
                <li key={section.slug}>
                  {variant === "panel" ? (
                    <Link
                      href={href}
                      onClick={() => setQuery("")}
                      aria-current={current ? "page" : undefined}
                      className={cn(
                        "focus-ring flex min-h-10 items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                        current
                          ? "bg-surface-2 text-foreground ring-1 ring-border"
                          : "text-text-secondary hover:bg-surface-2/70 hover:text-foreground",
                      )}
                    >
                      <Icon aria-hidden className={cn("h-4 w-4 shrink-0", current && "text-brand")} />
                      {section.title}
                    </Link>
                  ) : (
                    <Link
                      href={href}
                      onClick={() => setQuery("")}
                      aria-labelledby={`${ids}-${section.slug}-title`}
                      aria-describedby={`${ids}-${section.slug}-about`}
                      className="focus-ring flex min-h-14 items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3 transition-colors hover:bg-surface-2"
                    >
                      <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface-2 text-brand">
                        <Icon className="h-[18px] w-[18px]" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span id={`${ids}-${section.slug}-title`} className="block text-sm font-semibold text-foreground">
                          {section.title}
                        </span>
                        <span id={`${ids}-${section.slug}-about`} className="block text-xs text-text-secondary">
                          {section.description}
                        </span>
                      </span>
                      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-text-secondary" />
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      <div
        className={cn(
          "flex shrink-0 items-center gap-3",
          variant === "panel" ? "border-t border-border bg-card p-3" : "mt-4 rounded-2xl border border-border bg-card p-3",
        )}
      >
        <UserAvatar user={user} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-bold text-foreground">{name}</p>
          {user.displayName && <p className="truncate text-xs text-text-secondary">{user.email}</p>}
        </div>
        <button
          type="button"
          onClick={signOut}
          disabled={signingOut}
          className="focus-ring flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
        >
          <LogOut aria-hidden className="h-4 w-4" />
          Log out
        </button>
      </div>
    </div>
  );
}
