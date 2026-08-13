"use client";

import { useWorkspace } from "@/lib/useWorkspace";
import { useAuthActions } from "@convex-dev/auth/react";
import { api } from "@v1/backend/convex/_generated/api";
import type { Id } from "@v1/backend/convex/_generated/dataModel";
import { ConfirmDialog } from "@v1/ui/confirm-dialog";
import { PromptDialog } from "@v1/ui/prompt-dialog";
import { Separator } from "@v1/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@v1/ui/tooltip";
import { cn } from "@v1/ui/utils";
import { useMutation, useQuery } from "convex/react";
import {
  Boxes,
  ChevronDown,
  CreditCard,
  FolderOpen,
  Home,
  Leaf,
  ListChecks,
  LogOut,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Search,
  Settings,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { stripLocale } from "@/lib/locales";

/**
 * The product's navigation.
 *
 * WHAT CHANGED AND WHY
 *
 * This listed twelve destinations, six of which — Jobs, Platform, Billing and
 * the workspace switcher above them — belong to the Convex SaaS starter this
 * codebase grew out of. Nothing in the Ayurveda product reads or writes any of
 * them, and giving them equal billing with the consultation is most of why the
 * app read as a dashboard with a chatbot bolted on.
 *
 * They are NOT removed. Every route still exists at its old URL and every Convex
 * call still fires; they now sit in a collapsed "Workspace" disclosure at the
 * bottom, one click from anywhere. Prominence changed, capability did not.
 *
 * What moves up is the thing people are here for: start a consultation, and find
 * the one you had last week.
 */

// Kept together so the demoted set is obvious at a glance rather than scattered.
const WORKSPACE_NAV = [
  { href: "/jobs", label: "Jobs", icon: ListChecks },
  { href: "/platform", label: "Platform", icon: Boxes },
  { href: "/settings/billing", label: "Billing", icon: CreditCard },
];

const PRODUCT_NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/files", label: "Reports", icon: FolderOpen },
  { href: "/settings", label: "Settings", icon: Settings },
];

const COLLAPSE_KEY = "ayur.sidebar.collapsed";

/**
 * Which item is "here" — the LONGEST match, not every match.
 *
 * `/settings/billing` is inside `/settings`, so a plain prefix test lights up
 * two items and the highlight stops meaning anything.
 */
function activeHrefFor(pathname: string, hrefs: string[]): string | undefined {
  const path = stripLocale(pathname);
  return hrefs
    .filter((href) =>
      href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`),
    )
    .sort((a, b) => b.length - a.length)[0];
}

function NavLink({
  href,
  label,
  icon: Icon,
  active,
  collapsed,
  onNavigate,
  prefetch,
}: {
  href: string;
  label: string;
  icon: typeof Home;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
  prefetch?: boolean;
}) {
  const link = (
    <Link
      href={href}
      prefetch={prefetch}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      // When collapsed the label is gone from the screen but must stay in the
      // accessibility tree, or the whole navigation becomes unlabelled buttons.
      aria-label={collapsed ? label : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-lg py-2 text-sm transition-colors",
        collapsed ? "justify-center px-0" : "px-2.5",
        active
          ? "bg-brand-soft font-medium text-brand"
          : "text-text-secondary hover:bg-surface-2 hover:text-foreground",
      )}
    >
      <Icon aria-hidden className="h-4 w-4 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  );

  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

function SidebarBody({
  onNavigate,
  collapsed,
  onToggleCollapse,
}: {
  onNavigate?: () => void;
  collapsed: boolean;
  onToggleCollapse?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuthActions();
  const user = useQuery(api.users.getUser);
  const { workspaces, current, select } = useWorkspace();
  const sessions = useQuery(api.chats.listSessions) ?? [];
  const rename = useMutation(api.chats.rename);
  const remove = useMutation(api.chats.remove);

  const [wsOpen, setWsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [activeC, setActiveC] = useState<string | null>(null);

  // Dialog state replaces window.prompt / window.confirm. Held here rather than
  // per row so one dialog instance serves the whole list.
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState<{ id: string; title: string } | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined")
      setActiveC(new URLSearchParams(window.location.search).get("c"));
  }, [pathname]);

  const filtered = sessions.filter((s) =>
    s.title.toLowerCase().includes(search.toLowerCase()),
  );
  const productActive = activeHrefFor(
    pathname,
    PRODUCT_NAV.map((i) => i.href),
  );
  const wsActive = activeHrefFor(
    pathname,
    WORKSPACE_NAV.map((i) => i.href),
  );
  const onConsult = stripLocale(pathname) === "/consult";

  return (
    <div
      className={cn(
        "flex h-full flex-col border-r border-border bg-surface transition-[width] duration-200",
        collapsed ? "w-16" : "w-64",
      )}
    >
      {/* Brand + collapse control */}
      <div
        className={cn(
          "flex h-14 shrink-0 items-center border-b border-border",
          collapsed ? "justify-center px-2" : "gap-2.5 px-4",
        )}
      >
        <Link href="/" onClick={onNavigate} className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand text-brand-foreground"
          >
            <Leaf className="h-4 w-4" />
          </span>
          {!collapsed && (
            <span className="leading-tight">
              <span className="block font-display text-sm font-semibold text-foreground">
                Ayurveda
              </span>
              <span className="block text-2xs text-text-secondary">by Ollasoftware</span>
            </span>
          )}
        </Link>
        {onToggleCollapse && !collapsed && (
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label="Collapse sidebar"
            className="ml-auto hidden rounded-md p-1.5 text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground md:block"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      {collapsed && onToggleCollapse && (
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label="Expand sidebar"
          className="mx-auto mt-2 rounded-md p-1.5 text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </button>
      )}

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
        {/* The one thing this product is for. */}
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Link
                href="/consult"
                onClick={onNavigate}
                aria-label="New consultation"
                className="grid h-10 w-10 shrink-0 place-items-center self-center rounded-xl bg-brand text-brand-foreground elev-1 transition hover:brightness-110"
              >
                <Plus aria-hidden className="h-4 w-4" />
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right">New consultation</TooltipContent>
          </Tooltip>
        ) : (
          <Link
            href="/consult"
            onClick={onNavigate}
            className="flex items-center justify-center gap-2 rounded-xl bg-brand px-3 py-2.5 text-sm font-semibold text-brand-foreground elev-1 transition hover:brightness-110 hover:elev-2"
          >
            <Plus aria-hidden className="h-4 w-4" /> New consultation
          </Link>
        )}

        {!collapsed && (
          <>
            {/* Chat history. No disclosure any more: it is the main content of
                this sidebar, not a section of it, and collapsing it by default
                hid the single most useful thing here. */}
            <div className="min-h-0 flex-1">
              <div className="mb-1.5 flex items-center justify-between px-1">
                <h2 className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
                  Consultations
                </h2>
                {sessions.length > 0 && (
                  <span className="font-mono text-2xs tabular-nums text-text-secondary">
                    {sessions.length}
                  </span>
                )}
              </div>

              {sessions.length > 3 && (
                <div className="relative mb-1.5">
                  <Search
                    aria-hidden
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-secondary"
                  />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search…"
                    aria-label="Search consultations"
                    className="w-full rounded-lg border border-border bg-background py-1.5 pl-8 pr-2 text-xs outline-none transition-colors focus:border-brand/50"
                  />
                </div>
              )}

              <div className="space-y-0.5">
                {filtered.length === 0 && (
                  <p className="px-2 py-3 text-xs leading-relaxed text-text-secondary">
                    {sessions.length === 0
                      ? "Your consultations appear here once you describe what's troubling you."
                      : "No consultation matches that."}
                  </p>
                )}
                {filtered.map((s) => {
                  const active = activeC === s.sessionId && onConsult;
                  return (
                    <div
                      key={s.sessionId}
                      className={cn(
                        "group flex items-center gap-1 rounded-lg transition-colors",
                        active
                          ? "bg-brand-soft text-brand"
                          : "text-text-secondary hover:bg-surface-2",
                      )}
                    >
                      <Link
                        href={`/consult?c=${s.sessionId}`}
                        onClick={() => {
                          setActiveC(s.sessionId);
                          onNavigate?.();
                        }}
                        aria-current={active ? "page" : undefined}
                        className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-sm"
                      >
                        <MessageSquare aria-hidden className="h-3.5 w-3.5 shrink-0 opacity-60" />
                        <span className="truncate">{s.title}</span>
                      </Link>
                      {/* `focus-within` as well as `group-hover`: hover-only
                          controls are unreachable by keyboard, so these two
                          buttons did not exist for anyone tabbing the list. */}
                      <span className="flex shrink-0 items-center gap-0.5 pr-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={() => setRenaming({ id: s.sessionId, title: s.title })}
                          aria-label={`Rename “${s.title}”`}
                          className="rounded p-1 transition-colors hover:bg-foreground/10"
                        >
                          <Pencil aria-hidden className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleting({ id: s.sessionId, title: s.title })}
                          aria-label={`Delete “${s.title}”`}
                          className="rounded p-1 text-destructive transition-colors hover:bg-destructive/10"
                        >
                          <Trash2 aria-hidden className="h-3 w-3" />
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <Separator />
          </>
        )}

        {/* The product's own destinations. */}
        <nav aria-label="Main" className="space-y-0.5">
          {PRODUCT_NAV.map((item) => (
            <NavLink
              key={item.href}
              {...item}
              active={item.href === productActive}
              collapsed={collapsed}
              onNavigate={onNavigate}
            />
          ))}
        </nav>

        {/* Everything inherited from the SaaS starter, demoted but intact. */}
        {!collapsed && (
          <div>
            <button
              type="button"
              aria-expanded={wsOpen}
              onClick={() => setWsOpen((v) => !v)}
              className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-2xs font-semibold uppercase tracking-wider text-text-secondary transition-colors hover:text-foreground"
            >
              Workspace
              <ChevronDown
                aria-hidden
                className={cn("h-3.5 w-3.5 transition-transform", !wsOpen && "-rotate-90")}
              />
            </button>
            {wsOpen && (
              <div className="mt-1 space-y-1">
                {workspaces.length > 0 && (
                  <select
                    value={current ?? ""}
                    onChange={(e) => select(e.target.value as Id<"workspaces">)}
                    aria-label="Select workspace"
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                  >
                    {workspaces.map((w) => (
                      <option key={w._id} value={w._id}>
                        {w.name} ({w.role})
                      </option>
                    ))}
                  </select>
                )}
                {WORKSPACE_NAV.map((item) => (
                  <NavLink
                    key={item.href}
                    {...item}
                    active={item.href === wsActive}
                    collapsed={false}
                    onNavigate={onNavigate}
                    prefetch={false}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Account */}
      <div className={cn("shrink-0 border-t border-border p-3", collapsed && "px-2")}>
        {!collapsed && (
          <div className="mb-2 flex items-center gap-2">
            {user?.avatarUrl ? (
              // biome-ignore lint/a11y/useAltText: decorative — the name is beside it
              <img src={user.avatarUrl} alt="" className="h-8 w-8 rounded-full object-cover" />
            ) : (
              <span
                aria-hidden
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-soft font-medium text-brand"
              >
                {(user?.name ?? "?").charAt(0).toUpperCase()}
              </span>
            )}
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">
                {user?.name || "—"}
              </p>
              <p className="truncate text-xs text-text-secondary">{user?.email}</p>
            </div>
          </div>
        )}
        <div className={cn("flex items-center", collapsed ? "justify-center" : "justify-between")}>
          {!collapsed && <ThemeSwitcher />}
          <button
            type="button"
            onClick={async () => {
              await signOut();
              // Navigate explicitly: without this the current page stays
              // rendered until something else triggers a request for the
              // middleware to catch.
              router.replace("/login");
              router.refresh();
            }}
            aria-label="Log out"
            className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1.5 text-xs text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <LogOut aria-hidden className="h-4 w-4 shrink-0" />
            {!collapsed && "Log out"}
          </button>
        </div>
      </div>

      <PromptDialog
        open={renaming !== null}
        onOpenChange={(open) => !open && setRenaming(null)}
        title="Rename consultation"
        label="Name"
        initialValue={renaming?.title ?? ""}
        submitLabel="Rename"
        onSubmit={(title) => {
          if (renaming) rename({ sessionId: renaming.id, title });
          setRenaming(null);
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this consultation?"
        // Names the chat. `window.confirm` could not — it renders plain text
        // only — so people were confirming a permanent delete without being
        // shown what they were deleting.
        description={
          <>
            <span className="font-medium text-foreground">“{deleting?.title}”</span> and its
            messages will be permanently removed. This cannot be undone.
          </>
        }
        confirmLabel="Delete"
        destructive
        onConfirm={() => {
          if (deleting) {
            remove({ sessionId: deleting.id });
            if (activeC === deleting.id) router.push("/consult");
          }
          setDeleting(null);
        }}
      />
    </div>
  );
}

export function Sidebar() {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  // Restore the rail state after mount rather than during render: reading
  // localStorage while rendering makes the server and client disagree and React
  // throws a hydration error.
  useEffect(() => {
    setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
  }, []);

  const toggleCollapse = () => {
    setCollapsed((value) => {
      window.localStorage.setItem(COLLAPSE_KEY, value ? "0" : "1");
      return !value;
    });
  };

  // Escape closes the mobile drawer. Radix gives dialogs this for free; this
  // drawer is hand-rolled and had no keyboard dismissal at all.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <div className="flex h-14 items-center gap-3 border-b border-border bg-surface px-4 md:hidden">
        <button
          type="button"
          aria-label="Open menu"
          aria-expanded={open}
          onClick={() => setOpen(true)}
          className="rounded-md p-1.5 transition-colors hover:bg-surface-2"
        >
          <Menu aria-hidden className="h-5 w-5" />
        </button>
        <span
          aria-hidden
          className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-brand-foreground"
        >
          <Leaf className="h-4 w-4" />
        </span>
        <span className="font-display text-sm font-semibold text-foreground">Ayurveda</span>
      </div>

      <aside className="sticky top-0 hidden h-dvh shrink-0 md:block">
        <SidebarBody collapsed={collapsed} onToggleCollapse={toggleCollapse} />
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 cursor-default bg-foreground/50"
            onClick={() => setOpen(false)}
          />
          <div className="absolute left-0 top-0 h-full elev-3">
            {/* Was positioned `-right-9`, i.e. OUTSIDE the drawer, floating over
                the backdrop with white text on whatever happened to be behind
                it. Now inside, on a real surface. */}
            <button
              type="button"
              aria-label="Close menu"
              className="absolute right-2 top-3 z-10 rounded-md p-1.5 text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground"
              onClick={() => setOpen(false)}
            >
              <X aria-hidden className="h-5 w-5" />
            </button>
            <SidebarBody collapsed={false} onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
