"use client";

import { api } from "@v1/backend/convex/_generated/api";
import { useMutation, useQuery } from "convex/react";
import { Bell } from "lucide-react";
import { useState } from "react";

/**
 * Visual pass only — the open/close mechanism, the mark-all-read-on-open call
 * and the invisible backdrop button are all unchanged.
 *
 * What changed is colour. This file carried three measured contrast failures
 * against `--card`: `text-primary/30` on the timestamps (~1.4:1),
 * `text-primary/50` on the bodies (~2.4:1) and `text-primary/40` on the empty
 * state (~1.9:1). `--primary` is the near-black TEXT colour, so those were
 * opacity-hidden colour decisions — exactly what `--text-secondary` exists to
 * name. The count pill was `bg-red-500`/`text-white`, two raw palette values
 * in a product whose README forbids them.
 */
export function NotificationsBell() {
  const notifications = useQuery(api.notifications.myNotifications);
  const unread = useQuery(api.notifications.unreadCount) ?? 0;
  const markAllRead = useMutation(api.notifications.markAllRead);
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Notifications"
        className="focus-ring relative grid h-9 w-9 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground"
        onClick={() => {
          const next = !open;
          setOpen(next);
          if (next && unread > 0) void markAllRead();
        }}
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          // `ring-2 ring-background` cuts a gap between the pill and the bell
          // glyph so the two do not read as one smudged shape.
          <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-destructive px-1 text-2xs font-semibold leading-none text-destructive-foreground ring-2 ring-background">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-label="Close notifications"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          {/* max-w clamp: 288px anchored right in a `px-4` topbar leaves only
              ~28px of clearance at 375px, and none below that. */}
          <div className="absolute right-0 z-50 mt-2 w-72 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-border bg-popover p-1.5 elev-3">
            <div className="px-2 py-1.5 text-2xs font-semibold uppercase tracking-wider text-text-secondary">
              Notifications
            </div>
            {/* No `divide-y`: hairlines between padded rows inside a rounded
                popover read as a table rather than a feed. */}
            <div className="scrollbar-subtle max-h-80 space-y-0.5 overflow-y-auto">
              {notifications?.length ? (
                notifications.map((n) => (
                  <div key={n._id} className="rounded-md px-2.5 py-2">
                    <p className="text-sm font-medium text-foreground">
                      {n.title}
                    </p>
                    {n.body && (
                      <p className="mt-0.5 text-xs leading-relaxed text-text-secondary">
                        {n.body}
                      </p>
                    )}
                    <time
                      dateTime={new Date(n.createdAt).toISOString()}
                      className="mt-1 block text-2xs text-text-secondary/80"
                    >
                      {new Date(n.createdAt).toLocaleString()}
                    </time>
                  </div>
                ))
              ) : (
                <div className="px-2.5 py-8 text-center">
                  <span
                    aria-hidden
                    className="mx-auto mb-2 grid h-9 w-9 place-items-center rounded-xl bg-surface-2 text-text-secondary"
                  >
                    <Bell className="h-4 w-4" />
                  </span>
                  <p className="text-sm font-medium text-foreground">
                    No notifications yet
                  </p>
                  <p className="mt-0.5 text-xs leading-relaxed text-text-secondary">
                    Job results and workspace invites appear here.
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
