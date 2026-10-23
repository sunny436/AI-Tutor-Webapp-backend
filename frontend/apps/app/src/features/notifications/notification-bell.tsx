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
import { clearNotifications, getNotifications, markNotificationsRead } from "@/lib/api/progress";
import type { AppNotification, NotificationList } from "@/lib/api/types";
import { relativeTime } from "@/lib/time";
import { unreadBadge } from "./celebrate";

/**
 * The header's bell: every in-app notification (streak reminders and milestones, security
 * alerts, reminders the worker plans), newest first. Plain text only. A milestone is celebrated
 * where it is reached (features/streak/celebrations), never again here. Fetched when shown, when
 * the window regains focus (not within FRESH_MS of the last load) and after a reply finishes; no
 * polling. Opening it reads nothing:
 * choosing a notification marks that one read, "Read all" marks every one read (also those
 * beyond the 30 shown) and "Clear all" empties it; the server keeps both after a reload. If it
 * can't load, the bell stays and says so; the header keeps working.
 */
/** A window focused again this soon after the last load (switching windows and back) asks nothing. */
const FRESH_MS = 15_000;

export function NotificationBell() {
  const [list, setList] = useState<NotificationList | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // Each load and each change made here takes a number; only the latest load's list is shown, so
  // a list fetched before a change never puts back what the change removed.
  const latest = useRef(0);
  const loadedAt = useRef(0);

  const load = useCallback(async () => {
    const mine = ++latest.current;
    try {
      const next = await getNotifications();
      if (mine !== latest.current) return;
      loadedAt.current = Date.now();
      setList(next);
      setFailed(false);
    } catch {
      if (mine === latest.current) setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
    const reload = () => void load();
    const onFocus = () => {
      if (Date.now() - loadedAt.current >= FRESH_MS) void load();
    };
    window.addEventListener("focus", onFocus);
    window.addEventListener(LEARNING_EVENT, reload);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener(LEARNING_EVENT, reload);
    };
  }, [load]);

  const unread = list?.unreadCount ?? 0;
  const badge = unreadBadge(unread);

  /** Show the change at once, make it on the server, then show the server's list (either way). */
  const change = async (shown: (current: NotificationList) => NotificationList, request: () => Promise<void>, failure: string) => {
    latest.current += 1; // whatever is loading now was asked for before this change
    setList((current) => current && shown(current));
    try {
      await request();
    } catch {
      toast.error(failure);
    } finally {
      void load();
    }
  };

  const changeAll = async (shown: (current: NotificationList) => NotificationList, request: () => Promise<void>, failure: string) => {
    if (busy) return;
    setBusy(true);
    await change(shown, request, failure);
    setBusy(false);
  };

  const readAll = () =>
    changeAll(
      (current) => ({
        items: current.items.map((item) => ({ ...item, readAt: item.readAt ?? new Date().toISOString() })),
        unreadCount: 0,
      }),
      () => markNotificationsRead(),
      "Couldn't mark your notifications read. Try again.",
    );

  const clearAll = () =>
    changeAll(() => ({ items: [], unreadCount: 0 }), clearNotifications, "Couldn't clear your notifications. Try again.");

  const readOne = (chosen: AppNotification) => {
    if (chosen.readAt !== null) return;
    void change(
      (current) => ({
        items: current.items.map((item) => (item.id === chosen.id ? { ...item, readAt: new Date().toISOString() } : item)),
        unreadCount: Math.max(0, current.unreadCount - 1),
      }),
      () => markNotificationsRead([chosen.id]),
      "Couldn't mark that notification read.",
    );
  };

  return (
    <DropdownMenu
      // Not modal: the page stays in the accessibility tree while the list is open (a modal menu
      // hides it with aria-hidden while its controls remain focusable).
      modal={false}
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
              className="absolute -right-1 -top-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-destructive px-1 text-[10px] font-bold leading-none text-destructive-foreground motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-75 duration-base ease-enter"
            >
              {badge}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[min(22rem,calc(100vw-1.5rem))] p-0">
        <div className="flex items-center justify-between gap-2 px-3 py-2">
          <DropdownMenuLabel className="p-0 text-sm font-semibold text-foreground">Notifications</DropdownMenuLabel>
          {list && list.items.length > 0 && (
            <div className="flex shrink-0 items-center gap-1">
              {/* Menu items, so the keyboard reaches them; choosing one keeps the list open. */}
              <DropdownMenuItem
                disabled={busy || unread === 0}
                onSelect={(event) => {
                  event.preventDefault();
                  void readAll();
                }}
                className="h-8 px-2 text-xs font-medium text-brand"
              >
                Read all
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={busy}
                onSelect={(event) => {
                  event.preventDefault();
                  void clearAll();
                }}
                className="h-8 px-2 text-xs font-medium text-text-secondary"
              >
                Clear all
              </DropdownMenuItem>
            </div>
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
                <DropdownMenuItem
                  key={item.id}
                  asChild
                  onSelect={() => readOne(item)}
                  className="cursor-pointer items-start px-3 py-2.5"
                >
                  <Link href={item.link}>{content}</Link>
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem key={item.id} onSelect={() => readOne(item)} className="items-start px-3 py-2.5">
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
