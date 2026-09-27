"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@v1/ui/dropdown-menu";
import { cn } from "@v1/ui/utils";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { LEARNING_EVENT } from "@/lib/activity";
import { getNotifications, markNotificationsRead } from "@/lib/api/progress";
import type { AppNotification, NotificationList } from "@/lib/api/types";
import { relativeTime } from "@/lib/time";
import { milestonesToCelebrate, unreadBadge } from "./celebrate";

const CELEBRATED_KEY = "padhai.celebrated";

function readCelebrated(): Set<string> {
  try {
    return new Set(JSON.parse(window.sessionStorage.getItem(CELEBRATED_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function saveCelebrated(ids: Set<string>): void {
  try {
    window.sessionStorage.setItem(CELEBRATED_KEY, JSON.stringify([...ids].slice(-50)));
  } catch {
    // storage unavailable: a milestone may be celebrated again after a reload, nothing worse
  }
}

/**
 * The header's bell: every in-app notification (streak reminders and milestones, security
 * alerts, reminders the worker plans), newest first. Plain text only. Fetched when shown, when
 * the window regains focus and after a reply finishes; no polling. Opening it marks what it
 * shows as read. If it can't load, the bell stays and says so; the header keeps working.
 */
export function NotificationBell() {
  const [list, setList] = useState<NotificationList | null>(null);
  const [failed, setFailed] = useState(false);
  const loading = useRef(false);

  const load = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    try {
      const next = await getNotifications();
      setList(next);
      setFailed(false);
      const celebrated = readCelebrated();
      for (const milestone of milestonesToCelebrate(next.items, celebrated)) {
        toast(milestone.title, { description: milestone.body, duration: 5000 });
        celebrated.add(milestone.id);
      }
      saveCelebrated(celebrated);
    } catch {
      setFailed(true);
    } finally {
      loading.current = false;
    }
  }, []);

  useEffect(() => {
    void load();
    const reload = () => void load();
    window.addEventListener("focus", reload);
    window.addEventListener(LEARNING_EVENT, reload);
    return () => {
      window.removeEventListener("focus", reload);
      window.removeEventListener(LEARNING_EVENT, reload);
    };
  }, [load]);

  const unread = list?.unreadCount ?? 0;
  const badge = unreadBadge(unread);

  const markShownRead = (items: AppNotification[]) => {
    const ids = items.filter((item) => item.readAt === null).map((item) => item.id);
    if (!ids.length) return;
    const now = new Date().toISOString();
    setList((current) =>
      current && {
        items: current.items.map((item) => (ids.includes(item.id) ? { ...item, readAt: now } : item)),
        unreadCount: Math.max(0, current.unreadCount - ids.length),
      },
    );
    markNotificationsRead(ids).catch(() => void load());
  };

  const markAll = () => {
    setList((current) => current && { items: current.items.map((item) => ({ ...item, readAt: item.readAt ?? new Date().toISOString() })), unreadCount: 0 });
    markNotificationsRead().catch(() => void load());
  };

  return (
    <DropdownMenu
      // Not modal: the page stays in the accessibility tree while the list is open (a modal menu
      // hides it with aria-hidden while its controls remain focusable).
      modal={false}
      onOpenChange={(open) => {
        if (open && list) markShownRead(list.items);
      }}
    >
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          className="focus-ring relative grid h-9 w-9 shrink-0 place-items-center rounded-full border border-border bg-card text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          <Bell aria-hidden className="h-4 w-4" />
          {badge && (
            <span
              aria-hidden
              className="absolute -right-1 -top-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-destructive px-1 text-[10px] font-bold leading-none text-destructive-foreground"
            >
              {badge}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[min(22rem,calc(100vw-1.5rem))] p-0">
        <div className="flex items-center justify-between px-3 py-2.5">
          <DropdownMenuLabel className="p-0 text-sm font-semibold text-foreground">Notifications</DropdownMenuLabel>
          {list?.items.some((item) => item.readAt === null) && (
            <button
              type="button"
              onClick={markAll}
              className="focus-ring rounded text-xs font-medium text-brand hover:underline"
            >
              Mark all as read
            </button>
          )}
        </div>
        <DropdownMenuSeparator className="m-0" />
        <div className="max-h-[min(24rem,70vh)] overflow-y-auto py-1">
          {failed && !list ? (
            <div className="px-3 py-6 text-center text-sm text-text-secondary">
              Couldn't load notifications.{" "}
              <button type="button" onClick={() => void load()} className="focus-ring rounded font-medium text-brand underline">
                Try again
              </button>
            </div>
          ) : !list ? (
            <p className="px-3 py-6 text-center text-sm text-text-secondary">Loading…</p>
          ) : list.items.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-text-secondary">You're all caught up.</p>
          ) : (
            list.items.map((item) => {
              const content = (
                <div key={item.id} className="flex w-full min-w-0 gap-2.5">
                  <span
                    aria-hidden
                    className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", item.readAt ? "bg-transparent" : "bg-brand")}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-foreground">{item.title}</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-text-secondary">{item.body}</span>
                    <span className="mt-1 block text-2xs text-text-secondary">
                      {relativeTime(item.createdAt)}
                      {item.readAt ? "" : <span className="sr-only"> · unread</span>}
                    </span>
                  </span>
                </div>
              );
              return item.link ? (
                <DropdownMenuItem key={item.id} asChild className="cursor-pointer items-start px-3 py-2.5">
                  <Link href={item.link}>{content}</Link>
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem key={item.id} className="items-start px-3 py-2.5">
                  {content}
                </DropdownMenuItem>
              );
            })
          )}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
