"use client";

import { ConfirmDialog } from "@v1/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@v1/ui/dropdown-menu";
import { PromptDialog } from "@v1/ui/prompt-dialog";
import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import {
  BookOpenCheck,
  ChevronsUpDown,
  FolderOpen,
  LogOut,
  type LucideIcon,
  MessageSquare,
  Pencil,
  Plus,
  Search,
  Settings,
  Timer,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactElement, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { useConversations, useStores } from "@/features/chat/chat-context";
import { forgetAppPath } from "@/features/navigation/app-return";
import { DEFAULT_SECTION } from "@/features/settings/sections";
import { describeError } from "@/lib/api/errors";
import type { Conversation } from "@/lib/api/types";
import { TITLE_MAX } from "@/lib/api/types";
import { APP_NAME } from "@/lib/brand";
import { BrandLockup, BrandMark } from "./brand/brand-mark";
import { MarqueeTitle } from "./marquee-title";
import { hubItems, isActive } from "./nav-items";
import { usePreview } from "./preview-context";
import { useSignOut } from "./use-sign-out";
import { UserAvatar } from "./user-avatar";
import { useUser } from "./user-context";

/** Which conversation is on screen — from the URL only (no copy of it in state). */
export function activeConversationId(pathname: string | null): string | null {
  return /^\/c\/([0-9a-f-]{36})$/i.exec(pathname ?? "")?.[1] ?? null;
}

const COLLAPSE_KEY = "aichat.sidebar.collapsed";
const COLLAPSE_EVENT = "aichat:sidebar-collapse";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false; // storage unavailable: stay expanded
  }
}

function subscribeCollapsed(onChange: () => void): () => void {
  window.addEventListener(COLLAPSE_EVENT, onChange);
  return () => window.removeEventListener(COLLAPSE_EVENT, onChange);
}

/**
 * Expanded on the server and while hydrating (storage is unknown there), then the saved value.
 * Read synchronously on a client-side mount, so the rail doesn't flash open when the app shell
 * comes back after Settings.
 */
export function useCollapsedSidebar() {
  const collapsed = useSyncExternalStore(subscribeCollapsed, readCollapsed, () => false);
  const toggle = () => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? "0" : "1");
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event(COLLAPSE_EVENT));
  };
  return { collapsed, toggle };
}

/** Where each copy of the sidebar was scrolled, kept while the app shell is away (Settings). */
const scrollMemory = new Map<string, number>();

/** In the collapsed rail a control is an icon only, so it names itself on hover and focus. */
function RailTip({ label, collapsed, children }: { label: string; collapsed: boolean; children: ReactElement }) {
  if (!collapsed) return children;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * The brand, "Ask New Doubt", the Learning Hub (only when there are tools besides the chat), the
 * chat list ("Recent Doubts") and the account. Rendered in the desktop rail and inside the mobile drawer
 * (`onNavigate` closes the drawer). The collapse control lives in the header.
 */
/** A sidebar place (My Learning, File Library, Study Activity): its page and everything under it. */
function PlaceLink({
  href,
  label,
  icon: Icon,
  collapsed,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const current = pathname === href || pathname?.startsWith(`${href}/`);
  return (
    <RailTip label={label} collapsed={collapsed}>
      <Link
        href={href}
        onClick={onNavigate}
        aria-current={current ? "page" : undefined}
        aria-label={collapsed ? label : undefined}
        className={cn(
          "focus-ring flex items-center gap-3 rounded-xl text-sm font-semibold transition-colors",
          collapsed ? "h-11 w-11 justify-center" : "w-full px-3 py-2.5",
          current ? "bg-brand-soft text-brand" : "text-text-secondary hover:bg-surface-2 hover:text-foreground",
        )}
      >
        <Icon aria-hidden className="h-5 w-5 shrink-0" />
        {!collapsed && label}
      </Link>
    </RailTip>
  );
}

export function SidebarContent({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { chat, conversations } = useStores();
  const list = useConversations();
  const { user } = useUser();
  const preview = usePreview();
  const hub = hubItems(preview);
  const active = activeConversationId(pathname);
  const [search, setSearch] = useState("");
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const { signOut, signingOut } = useSignOut();
  // The drawer is the phone layout, where Settings opens on its list of sections.
  const variant = onNavigate ? "drawer" : "rail";
  const settingsHref = variant === "drawer" ? "/settings" : `/settings/${DEFAULT_SECTION}`;
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    element.scrollTop = scrollMemory.get(variant) ?? 0;
    const remember = () => scrollMemory.set(variant, element.scrollTop);
    element.addEventListener("scroll", remember, { passive: true });
    return () => element.removeEventListener("scroll", remember);
  }, [variant]);

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
    forgetAppPath(`/c/${target.id}`);
    if (active === target.id) router.push("/");
    try {
      await chat.deleteConversation(target.id);
    } catch (error) {
      conversations.restore(target);
      toast.error(`Couldn't delete the chat. ${describeError(error).message}`);
    }
  };

  const name = user.displayName || user.email;

  return (
    <div
      className={cn(
        "flex h-full flex-col border-r border-border bg-card transition-[width] duration-slow ease-standard",
        collapsed ? "w-20" : "w-72 max-w-full",
      )}
    >
      {/* Outside the scrolling list: the brand stays in view, and a scrollbar never narrows the slogan's line. */}
      <div className={cn("flex shrink-0 items-center border-b border-border/70", collapsed ? "justify-center p-4" : "px-3 py-5")}>
        <Link href="/" onClick={onNavigate} className="focus-ring rounded-2xl">
          {collapsed ? (
            <>
              <BrandMark size={44} className="rounded-2xl" />
              <span className="sr-only">{APP_NAME}</span>
            </>
          ) : (
            <BrandLockup />
          )}
        </Link>
      </div>

      <div ref={scroller} className="scrollbar-subtle flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain">

        <div className={cn("shrink-0", collapsed ? "flex justify-center px-3 py-4" : "px-4 py-4")}>
          <RailTip label="Ask New Doubt" collapsed={collapsed}>
            <Link
              href="/"
              onClick={onNavigate}
              aria-label={collapsed ? "Ask New Doubt" : undefined}
              className={cn(
                "focus-ring group flex items-center justify-center gap-2 rounded-xl bg-brand font-semibold text-brand-foreground elev-1 transition hover:bg-brand-hover hover:elev-2 active:scale-[0.98]",
                collapsed ? "h-11 w-11" : "w-full px-4 py-3 text-sm",
              )}
            >
              <Plus aria-hidden className="h-5 w-5" />
              {!collapsed && "Ask New Doubt"}
            </Link>
          </RailTip>
        </div>

        {/* Places of their own, not Learning Hub items: your practice, the files the tutor can read, your study time. */}
        <div className={cn("shrink-0 space-y-1", collapsed ? "flex flex-col items-center px-3 pb-3" : "px-3 pb-3")}>
          <PlaceLink href="/learning" label="My Learning" icon={BookOpenCheck} collapsed={collapsed} onNavigate={onNavigate} />
          <PlaceLink href="/library" label="File Library" icon={FolderOpen} collapsed={collapsed} onNavigate={onNavigate} />
          <PlaceLink href="/study" label="Study Activity" icon={Timer} collapsed={collapsed} onNavigate={onNavigate} />
        </div>

        {hub.length > 0 && (
          <nav aria-labelledby="hub-heading" className={cn("shrink-0 space-y-1", collapsed ? "px-3" : "px-3")}>
            <h2
              id="hub-heading"
              className={cn(
                "mb-2 px-3 text-2xs font-semibold uppercase tracking-[0.08em] text-text-secondary",
                collapsed && "sr-only",
              )}
            >
              Learning Hub
            </h2>
            {hub.map((item) => {
              const Icon = item.icon;
              const current = isActive(item, pathname);
              return (
                <RailTip key={item.id} label={item.label} collapsed={collapsed}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={current ? "page" : undefined}
                    aria-label={collapsed ? item.label : undefined}
                    className={cn(
                      "focus-ring relative flex items-center rounded-xl text-left transition-[color,background-color,box-shadow]",
                      collapsed ? "mx-auto h-11 w-11 justify-center" : "w-full gap-3 px-3 py-2.5",
                      current
                        ? "bg-brand-soft font-semibold text-foreground"
                        : "text-text-secondary hover:bg-surface-2 hover:text-foreground",
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", current ? "bg-card text-brand" : item.accent)}
                    >
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    {!collapsed && (
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium leading-tight">{item.label}</span>
                        <span className="block truncate text-2xs text-text-secondary">
                          {item.description}
                        </span>
                      </span>
                    )}
                    {current && !collapsed && <span aria-hidden className="h-6 w-1 shrink-0 rounded-full bg-brand" />}
                  </Link>
                </RailTip>
              );
            })}
          </nav>
        )}

        {collapsed ? (
          <div className="min-h-0 flex-1" />
        ) : (
          <nav aria-labelledby="chats-heading" className="mt-5 flex min-h-[10rem] flex-1 flex-col">
            <div className="flex items-center justify-between px-6 pb-2">
              <h2 id="chats-heading" className="text-2xs font-semibold uppercase tracking-[0.08em] text-text-secondary">
                Recent Doubts
              </h2>
            </div>
            {list.items.length > 5 && (
              <div className="relative mx-4 mb-2">
                <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-secondary" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search chats"
                  aria-label="Search chats"
                  className="focus-field h-9 w-full rounded-xl border border-input bg-card pl-8 pr-2 text-sm transition-colors placeholder:text-text-secondary hover:border-text-secondary/40"
                />
              </div>
            )}
            <div className="px-3 pb-3">
              {list.status === "loading" && list.items.length === 0 ? (
                <SkeletonGroup label="Loading chats" className="space-y-1.5 pt-1">
                  {[0, 1, 2, 3].map((row) => (
                    <Skeleton key={row} className="h-9 w-full rounded-xl" />
                  ))}
                </SkeletonGroup>
              ) : list.status === "error" && list.items.length === 0 ? (
                <div className="px-3 py-3 text-sm text-text-secondary">
                  <p>Couldn't load your chats.</p>
                  <button
                    type="button"
                    onClick={() => void conversations.refresh()}
                    className="focus-ring mt-1 rounded text-sm font-medium text-brand underline underline-offset-2"
                  >
                    Try again
                  </button>
                </div>
              ) : visible.length === 0 ? (
                <p className="px-3 py-3 text-sm text-text-secondary">
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
                          "group flex items-center gap-1 rounded-xl transition-colors",
                          isActive ? "bg-brand-soft font-medium text-foreground" : "text-foreground/85 hover:bg-surface-2 hover:text-foreground",
                        )}
                      >
                        <Link
                          href={`/c/${item.id}`}
                          onClick={onNavigate}
                          aria-current={isActive ? "page" : undefined}
                          className="focus-ring-inset flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-xl px-3 text-sm"
                        >
                          <MessageSquare aria-hidden className={cn("h-3.5 w-3.5 shrink-0", isActive ? "text-brand" : "text-text-secondary")} />
                          <MarqueeTitle title={item.title} />
                        </Link>
                        {/* Always visible on touch; on hover/focus with a pointer. */}
                        <span className="flex shrink-0 items-center gap-0.5 pr-1 opacity-100 transition-opacity md:[@media(hover:hover)_and_(pointer:fine)]:opacity-0 md:focus-within:opacity-100 md:group-hover:opacity-100">
                          <button
                            type="button"
                            onClick={() => setRenaming(item)}
                            aria-label={`Rename “${item.title}”`}
                            className="focus-ring-inset grid h-7 w-7 place-items-center rounded-lg transition-colors hover:bg-foreground/10"
                          >
                            <Pencil aria-hidden className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleting(item)}
                            aria-label={`Delete “${item.title}”`}
                            className="focus-ring-inset grid h-7 w-7 place-items-center rounded-lg text-destructive transition-colors hover:bg-destructive/10"
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
                  className="focus-ring mt-2 w-full rounded-xl px-3 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
                >
                  {list.loadingMore ? "Loading…" : "Load more"}
                </button>
              )}
            </div>
          </nav>
        )}
      </div>

      {/* Only the account here: Settings and Log out are in its menu. */}
      <div className={cn("shrink-0 border-t border-border bg-card p-2", collapsed && "px-2")}>
        <DropdownMenu modal={false}>
          <RailTip label={name} collapsed={collapsed}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`Account: ${name}`}
                className={cn(
                  "focus-ring flex w-full items-center gap-3 rounded-xl p-1.5 text-left transition-colors hover:bg-surface-2 data-[state=open]:bg-surface-2",
                  collapsed && "justify-center",
                )}
              >
                <UserAvatar user={user} />
                {!collapsed && (
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-foreground">{name}</span>
                    {user.displayName && <span className="block truncate text-xs text-text-secondary">{user.email}</span>}
                  </span>
                )}
                {!collapsed && <ChevronsUpDown aria-hidden className="h-4 w-4 shrink-0 text-text-secondary" />}
              </button>
            </DropdownMenuTrigger>
          </RailTip>
          <DropdownMenuContent
            side="top"
            align="start"
            sideOffset={6}
            collisionPadding={8}
            className={cn("min-w-[12rem] p-1", !collapsed && "w-[var(--radix-dropdown-menu-trigger-width)]")}
          >
            <DropdownMenuItem asChild className="gap-2.5 font-medium">
              <Link href={settingsHref} onClick={onNavigate}>
                <Settings aria-hidden className="h-4 w-4 text-text-secondary" />
                Settings
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => void signOut()}
              disabled={signingOut}
              className="gap-2.5 font-medium text-destructive focus:bg-destructive/10 focus:text-destructive"
            >
              <LogOut aria-hidden className="h-4 w-4" />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
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
