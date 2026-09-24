"use client";

import { ConfirmDialog } from "@v1/ui/confirm-dialog";
import { PromptDialog } from "@v1/ui/prompt-dialog";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import { LogOut, MessageSquare, PanelLeftClose, PanelLeftOpen, Pencil, Plus, Search, Settings, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useConversations, useStores } from "@/features/chat/chat-context";
import { logout } from "@/lib/api/auth";
import { describeError } from "@/lib/api/errors";
import type { Conversation } from "@/lib/api/types";
import { TITLE_MAX } from "@/lib/api/types";
import { APP_NAME } from "@/lib/brand";
import { ThemeSwitcher } from "./theme-switcher";
import { useUser } from "./user-context";

/** Which conversation is on screen — from the URL only (no copy of it in state). */
export function activeConversationId(pathname: string | null): string | null {
  return /^\/c\/([0-9a-f-]{36})$/i.exec(pathname ?? "")?.[1] ?? null;
}

const COLLAPSE_KEY = "aichat.sidebar.collapsed";

export function useCollapsedSidebar() {
  const [collapsed, setCollapsed] = useState(false);
  // Read after mount: reading storage during render would mismatch hydration.
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      // storage unavailable: stay expanded
    }
  }, []);
  const toggle = () =>
    setCollapsed((value) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, value ? "0" : "1");
      } catch {
        // ignore
      }
      return !value;
    });
  return { collapsed, toggle };
}

/**
 * New chat, the conversation list, and the account. Rendered in the desktop rail
 * and inside the mobile drawer (`onNavigate` closes the drawer).
 */
export function SidebarContent({
  collapsed = false,
  onToggleCollapse,
  onNavigate,
}: {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { chat, conversations } = useStores();
  const list = useConversations();
  const { user } = useUser();
  const active = activeConversationId(pathname);
  const [search, setSearch] = useState("");
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return query ? list.items.filter((item) => item.title.toLowerCase().includes(query)) : list.items;
  }, [list.items, search]);

  const rename = async (title: string) => {
    const target = renaming;
    setRenaming(null);
    if (!target) return;
    try {
      await conversations.rename(target.id, title.slice(0, TITLE_MAX));
    } catch (error) {
      toast.error(`Couldn't rename the chat. ${describeError(error).message}`);
    }
  };

  const remove = async () => {
    const target = deleting;
    setDeleting(null);
    if (!target) return;
    conversations.remove(target.id);
    if (active === target.id) router.push("/");
    try {
      await chat.deleteConversation(target.id);
    } catch (error) {
      conversations.restore(target);
      toast.error(`Couldn't delete the chat. ${describeError(error).message}`);
    }
  };

  const signOut = async () => {
    setSigningOut(true);
    try {
      await logout();
    } catch (error) {
      setSigningOut(false);
      toast.error(describeError(error).message);
      return;
    }
    chat.reset();
    // A full load leaves nothing of the old session in memory.
    window.location.assign("/login");
  };

  const newChat = (
    <Link
      href="/"
      onClick={onNavigate}
      aria-label={collapsed ? "New chat" : undefined}
      className={cn(
        "focus-ring flex items-center justify-center gap-2 rounded-xl bg-brand font-semibold text-brand-foreground elev-1 transition hover:brightness-110",
        collapsed ? "h-10 w-10 self-center" : "px-3 py-2.5 text-sm",
      )}
    >
      <Plus aria-hidden className="h-4 w-4" />
      {!collapsed && "New chat"}
    </Link>
  );

  return (
    <div className={cn("flex h-full flex-col border-r border-border bg-surface", collapsed ? "w-16" : "w-72 max-w-full")}>
      <div className={cn("flex h-14 shrink-0 items-center border-b border-border", collapsed ? "justify-center px-2" : "gap-2.5 px-4")}>
        <Link href="/" onClick={onNavigate} className="focus-ring flex items-center gap-2.5 rounded-lg">
          <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand text-brand-foreground">
            <Sparkles className="h-4 w-4" />
          </span>
          {collapsed ? (
            <span className="sr-only">{APP_NAME}</span>
          ) : (
            <span className="font-display text-sm font-semibold text-foreground">{APP_NAME}</span>
          )}
        </Link>
      </div>

      <div className="flex shrink-0 flex-col px-3 pt-3">
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>{newChat}</TooltipTrigger>
            <TooltipContent side="right">New chat</TooltipContent>
          </Tooltip>
        ) : (
          newChat
        )}
      </div>

      {collapsed ? (
        <div className="min-h-0 flex-1" />
      ) : (
        <nav aria-labelledby="chats-heading" className="mt-4 flex min-h-0 flex-1 flex-col">
          <div className="flex items-center justify-between px-4 pb-1.5">
            <h2 id="chats-heading" className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
              Chats
            </h2>
          </div>
          {list.items.length > 5 && (
            <div className="relative mx-3 mb-1.5">
              <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-secondary" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search chats"
                aria-label="Search chats"
                className="focus-field h-8 w-full rounded-lg border border-border bg-background pl-8 pr-2 text-sm placeholder:text-text-secondary"
              />
            </div>
          )}
          <div className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto px-3 pb-3">
            {list.status === "loading" && list.items.length === 0 ? (
              <SkeletonGroup label="Loading chats" className="space-y-1.5 pt-1">
                {[0, 1, 2, 3].map((row) => (
                  <Skeleton key={row} className="h-8 w-full rounded-lg" />
                ))}
              </SkeletonGroup>
            ) : list.status === "error" && list.items.length === 0 ? (
              <div className="px-1 py-3 text-sm text-text-secondary">
                <p>Couldn't load your chats.</p>
                <button
                  type="button"
                  onClick={() => void conversations.refresh()}
                  className="focus-ring mt-1 rounded text-sm underline underline-offset-2 hover:text-foreground"
                >
                  Try again
                </button>
              </div>
            ) : visible.length === 0 ? (
              <p className="px-1 py-3 text-sm text-text-secondary">
                {list.items.length === 0 ? "Your chats will appear here." : "No chat matches that."}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {visible.map((item) => {
                  const isActive = item.id === active;
                  return (
                    <li
                      key={item.id}
                      className={cn(
                        "group flex items-center gap-1 rounded-lg transition-colors",
                        isActive ? "bg-brand-soft text-brand" : "text-text-secondary hover:bg-surface-2",
                      )}
                    >
                      <Link
                        href={`/c/${item.id}`}
                        onClick={onNavigate}
                        aria-current={isActive ? "page" : undefined}
                        className="focus-ring-inset flex h-9 min-w-0 flex-1 items-center gap-2 rounded-lg px-2.5 text-sm"
                      >
                        <MessageSquare aria-hidden className="h-3.5 w-3.5 shrink-0 opacity-60" />
                        <span className="truncate">{item.title}</span>
                      </Link>
                      {/* Always visible on touch; on hover/focus with a pointer. */}
                      <span className="flex shrink-0 items-center gap-0.5 pr-1 opacity-100 transition-opacity md:opacity-0 md:focus-within:opacity-100 md:group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={() => setRenaming(item)}
                          aria-label={`Rename “${item.title}”`}
                          className="focus-ring-inset grid h-7 w-7 place-items-center rounded-md transition-colors hover:bg-foreground/10"
                        >
                          <Pencil aria-hidden className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleting(item)}
                          aria-label={`Delete “${item.title}”`}
                          className="focus-ring-inset grid h-7 w-7 place-items-center rounded-md text-destructive transition-colors hover:bg-destructive/10"
                        >
                          <Trash2 aria-hidden className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            {list.nextCursor && !search && (
              <button
                type="button"
                onClick={() => void conversations.loadMore().catch((error) => toast.error(describeError(error).message))}
                disabled={list.loadingMore}
                className="focus-ring mt-2 w-full rounded-lg px-2 py-1.5 text-sm text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
              >
                {list.loadingMore ? "Loading…" : "Load more"}
              </button>
            )}
          </div>
        </nav>
      )}

      <div className={cn("shrink-0 border-t border-border p-3", collapsed && "px-2")}>
        {!collapsed && (
          <div className="mb-2.5 min-w-0 px-1">
            <p className="truncate text-sm font-medium text-foreground">{user.displayName || user.email}</p>
            {user.displayName && <p className="truncate text-xs text-text-secondary">{user.email}</p>}
          </div>
        )}
        <div className={cn("flex items-center gap-1", collapsed ? "flex-col" : "justify-between")}>
          <Link
            href="/settings"
            onClick={onNavigate}
            aria-label="Settings"
            aria-current={pathname === "/settings" ? "page" : undefined}
            className="focus-ring grid h-8 w-8 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <Settings aria-hidden className="h-4 w-4" />
          </Link>
          {!collapsed && <ThemeSwitcher />}
          {onToggleCollapse && (
            <button
              type="button"
              onClick={onToggleCollapse}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="focus-ring hidden h-8 w-8 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground md:grid"
            >
              {collapsed ? <PanelLeftOpen aria-hidden className="h-4 w-4" /> : <PanelLeftClose aria-hidden className="h-4 w-4" />}
            </button>
          )}
          <button
            type="button"
            onClick={signOut}
            disabled={signingOut}
            aria-label="Log out"
            className="focus-ring grid h-8 w-8 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
          >
            <LogOut aria-hidden className="h-4 w-4" />
          </button>
        </div>
      </div>

      <PromptDialog
        open={renaming !== null}
        onOpenChange={(open) => !open && setRenaming(null)}
        title="Rename chat"
        label="Name"
        initialValue={renaming?.title ?? ""}
        maxLength={TITLE_MAX}
        submitLabel="Rename"
        onSubmit={rename}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this chat?"
        description={
          <>
            <span className="font-medium text-foreground">“{deleting?.title}”</span> and all its messages will be
            permanently deleted.
          </>
        }
        confirmLabel="Delete"
        destructive
        onConfirm={remove}
      />
    </div>
  );
}
