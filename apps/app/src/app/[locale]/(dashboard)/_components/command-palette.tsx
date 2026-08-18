"use client";

import {
  Boxes,
  CreditCard,
  FolderOpen,
  Home,
  ListChecks,
  MessageSquare,
  Search,
  Settings,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

// The icons are the ones the sidebar already uses for the same destinations —
// the same place should look the same in both navigations. They are metadata,
// not new capability: every entry, its label and its href are unchanged.
const COMMANDS = [
  { label: "Chat", href: "/consult", icon: MessageSquare },
  { label: "Dashboard", href: "/", icon: Home },
  { label: "Jobs", href: "/jobs", icon: ListChecks },
  { label: "Platform", href: "/platform", icon: Boxes },
  { label: "Files", href: "/files", icon: FolderOpen },
  { label: "Settings", href: "/settings", icon: Settings },
  { label: "Billing", href: "/settings/billing", icon: CreditCard },
];

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!open) return null;
  const filtered = COMMANDS.filter((c) =>
    c.label.toLowerCase().includes(q.toLowerCase()),
  );
  const go = (href: string) => {
    setOpen(false);
    setQ("");
    router.push(href);
  };

  return (
    // `px-4` and `pt-20 sm:pt-32`: at 375px the panel was `w-full` with no
    // gutter, so it ran edge to edge. In landscape on a phone, 128px of top
    // padding plus a 288px list overflowed a 375px-tall viewport with nothing
    // to scroll, putting the last results permanently out of reach — hence the
    // `50dvh` cap on the list too.
    <div className="fixed inset-0 z-[100] flex items-start justify-center px-4 pt-20 sm:pt-32">
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 h-full w-full cursor-default bg-overlay/55 backdrop-blur-[2px]"
        onClick={() => setOpen(false)}
      />
      <div className="relative w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card elev-3">
        <div className="relative border-b border-border">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text-secondary"
          />
          <input
            // biome-ignore lint/a11y/noAutofocus: palette focus is expected
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Jump to…"
            aria-label="Jump to a page"
            onKeyDown={(e) => {
              if (e.key === "Enter" && filtered[0]) go(filtered[0].href);
            }}
            className="h-12 w-full bg-transparent pl-11 pr-4 text-base outline-none placeholder:text-text-secondary"
          />
        </div>
        <div className="scrollbar-subtle max-h-[min(18rem,50dvh)] overflow-y-auto p-1.5">
          {filtered.length ? (
            filtered.map((c, index) => (
              <button
                key={c.href}
                type="button"
                onClick={() => go(c.href)}
                // Enter has always gone to the first match. Nothing on screen
                // said so; this only makes the existing behaviour visible.
                className={`focus-ring-inset flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground transition-colors hover:bg-surface-2 ${
                  index === 0 ? "bg-surface-2 ring-1 ring-border" : ""
                }`}
              >
                <c.icon aria-hidden className="h-4 w-4 shrink-0 text-text-secondary" />
                {c.label}
              </button>
            ))
          ) : (
            <div className="px-3 py-10 text-center text-sm text-text-secondary">
              No results
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 border-t border-border bg-surface px-3 py-2 text-2xs text-text-secondary">
          <span>
            <kbd className="rounded border border-border bg-surface-2 px-1 py-0.5 font-mono">
              ↵
            </kbd>{" "}
            open
          </span>
          <span>
            <kbd className="rounded border border-border bg-surface-2 px-1 py-0.5 font-mono">
              esc
            </kbd>{" "}
            close
          </span>
        </div>
      </div>
    </div>
  );
}
