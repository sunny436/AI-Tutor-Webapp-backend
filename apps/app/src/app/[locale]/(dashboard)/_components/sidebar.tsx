"use client";

import { useWorkspace } from "@/lib/useWorkspace";
import { useAuthActions } from "@convex-dev/auth/react";
import { api } from "@v1/backend/convex/_generated/api";
import type { Id } from "@v1/backend/convex/_generated/dataModel";
import { useMutation, useQuery } from "convex/react";
import {
  Boxes,
  ChevronDown,
  CreditCard,
  FolderOpen,
  LayoutDashboard,
  Leaf,
  ListChecks,
  LogOut,
  Menu,
  MessageSquare,
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
import { ThemeSwitcher } from "./theme-switcher";

// One intelligent consultation replaces the old category list (General Health /
// Ayurveda / Yoga / Diet / Lifestyle / Wellness). Those were six doors into the
// same chat; the AI now works out what kind of consultation this is from what
// the user describes, so picking a category up front is meaningless.

// All original template pages  -  restored so every feature stays reachable.
const WORKSPACE_NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/jobs", label: "Jobs", icon: ListChecks },
  { href: "/platform", label: "Platform", icon: Boxes },
  { href: "/files", label: "Files", icon: FolderOpen },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/settings/billing", label: "Billing", icon: CreditCard },
];

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuthActions();
  const user = useQuery(api.users.getUser);
  const { workspaces, current, select } = useWorkspace();
  const sessions = useQuery(api.chats.listSessions) ?? [];
  const rename = useMutation(api.chats.rename);
  const remove = useMutation(api.chats.remove);

  const [wsOpen, setWsOpen] = useState(true);
  const [search, setSearch] = useState("");
  // Open by default: the history is the main reason to use this sidebar.
  const [chatOpen, setChatOpen] = useState(true);
  const [activeC, setActiveC] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") setActiveC(new URLSearchParams(window.location.search).get("c"));
  }, [pathname]);

  const filtered = sessions.filter((s) => s.title.toLowerCase().includes(search.toLowerCase()));

  const onRename = (e: React.MouseEvent, sessionId: string, title: string) => {
    e.preventDefault(); e.stopPropagation();
    const t = window.prompt("Rename chat", title);
    if (t && t.trim()) rename({ sessionId, title: t.trim() });
  };
  const onDelete = (e: React.MouseEvent, sessionId: string) => {
    e.preventDefault(); e.stopPropagation();
    if (window.confirm("Delete this chat? This cannot be undone.")) {
      remove({ sessionId });
      if (activeC === sessionId) router.push("/consult");
    }
  };

  return (
    <div className="flex h-full w-64 flex-col border-r border-border bg-card">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-4">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-emerald-400 to-teal-600 text-white"><Leaf className="h-4 w-4" /></span>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-primary">Ayurveda</div>
          <div className="text-[10px] tracking-wide text-primary/40">by Ollasoftware</div>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-3 py-3">
        {/* New chat */}
        <Link href="/consult" onClick={onNavigate}
          className="flex items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 px-3 py-2.5 text-sm font-semibold text-white shadow-md shadow-emerald-500/20 transition hover:brightness-105">
          <Plus className="h-4 w-4" /> New Chat
        </Link>

        {/* Chat  -  one disclosure that both opens the chat and holds its history.
            Previously "Chat" and "Recent Chats" were two separate blocks, which
            made the history look like a permanent fixture rather than something
            belonging to Chat. */}
        <div>
          <button
            type="button"
            onClick={() => setChatOpen((open) => !open)}
            aria-expanded={chatOpen}
            className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
              pathname === "/consult"
                ? "bg-emerald-500/10 font-medium text-emerald-700 dark:text-emerald-300"
                : "text-primary/70 hover:bg-primary/5"
            }`}
          >
            <MessageSquare className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            <span className="flex-1 text-left">Chat</span>
            {sessions.length > 0 && (
              <span className="rounded-full bg-primary/10 px-1.5 text-[10px] font-medium tabular-nums text-primary/50">
                {sessions.length}
              </span>
            )}
            <ChevronDown
              className={`h-3.5 w-3.5 shrink-0 text-primary/40 transition-transform duration-200 ${
                chatOpen ? "rotate-180" : ""
              }`}
            />
          </button>

          {chatOpen && (
        <div className="mt-1 border-l border-border/60 pl-2">
          <div className="relative mb-1.5">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-primary/30" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search chats..."
              className="w-full rounded-lg border border-border bg-background py-1.5 pl-8 pr-2 text-xs outline-none focus:border-emerald-500/50" />
          </div>
          <div className="space-y-0.5">
            {filtered.length === 0 && <p className="px-2 py-2 text-xs text-primary/40">No chats yet.</p>}
            {filtered.map((s) => {
              const active = activeC === s.sessionId;
              return (
                <Link key={s.sessionId} href={`/consult?c=${s.sessionId}`} onClick={() => { setActiveC(s.sessionId); onNavigate?.(); }}
                  className={`group flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition ${active ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "text-primary/70 hover:bg-primary/5"}`}>
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
                  <span className="flex-1 truncate">{s.title}</span>
                  <span className="hidden shrink-0 items-center gap-1 group-hover:flex">
                    <button onClick={(e) => onRename(e, s.sessionId, s.title)} className="rounded p-0.5 hover:bg-primary/10" title="Rename"><Pencil className="h-3 w-3" /></button>
                    <button onClick={(e) => onDelete(e, s.sessionId)} className="rounded p-0.5 text-rose-500 hover:bg-rose-500/10" title="Delete"><Trash2 className="h-3 w-3" /></button>
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
          )}
        </div>

        {/* Workspace (all original template features) */}
        <div>
          <button onClick={() => setWsOpen((v) => !v)} className="flex w-full items-center justify-between px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary/40 hover:text-primary/60">
            Workspace
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${wsOpen ? "" : "-rotate-90"}`} />
          </button>
          {wsOpen && (
            <div className="mt-1 space-y-1">
              <select
                value={current ?? ""}
                onChange={(e) => select(e.target.value as Id<"workspaces">)}
                className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
              >
                {workspaces.length === 0 && <option>...</option>}
                {workspaces.map((w) => (
                  <option key={w._id} value={w._id}>{w.name} ({w.role})</option>
                ))}
              </select>
              {WORKSPACE_NAV.map((item) => {
                const active = pathname === item.href;
                const Icon = item.icon;
                return (
                  <Link key={item.href} href={item.href} prefetch={false} onClick={onNavigate}
                    className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${active ? "bg-emerald-500/10 font-medium text-emerald-700 dark:text-emerald-300" : "text-primary/70 hover:bg-primary/5"}`}>
                    <Icon className="h-4 w-4 shrink-0" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* User footer */}
      <div className="border-t border-border p-3">
        <div className="mb-2 flex items-center gap-2">
          {user?.avatarUrl ? (
            // biome-ignore lint/a11y/useAltText: decorative avatar
            <img src={user.avatarUrl} alt="" className="h-8 w-8 rounded-full object-cover" />
          ) : (
            <span className="h-8 w-8 shrink-0 rounded-full bg-gradient-to-br from-emerald-400 via-teal-300 to-cyan-400" />
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-primary/80">{user?.name || " - "}</p>
            <p className="truncate text-xs text-primary/50">{user?.email}</p>
          </div>
        </div>
        <div className="flex items-center justify-between">
          <ThemeSwitcher />
          <button
            type="button"
            onClick={async () => {
              await signOut();
              // Navigate explicitly: without this the current page stays rendered
              // until something else triggers a request for the middleware to catch.
              router.replace("/login");
              router.refresh();
            }}
            // `shrink-0` and `whitespace-nowrap` because this sits beside the
            // theme selector in a flex row: without them "Log out" wrapped onto
            // two lines as soon as the selector claimed the space.
            className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1.5 text-xs text-primary/60 transition-colors hover:bg-primary/5 hover:text-primary"
          >
            <LogOut className="h-4 w-4 shrink-0" /> Log out
          </button>
        </div>
      </div>
    </div>
  );
}

export function Sidebar() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="flex h-14 items-center gap-3 border-b border-border bg-card px-4 md:hidden">
        <button type="button" aria-label="Open menu" onClick={() => setOpen(true)}><Menu className="h-5 w-5" /></button>
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-emerald-400 to-teal-600 text-white"><Leaf className="h-4 w-4" /></span>
        <span className="text-sm font-semibold text-primary">Ayurveda</span>
      </div>

      <aside className="sticky top-0 hidden h-screen shrink-0 md:block"><SidebarBody /></aside>

      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button type="button" aria-label="Close menu" className="absolute inset-0 cursor-default bg-black/50" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-0 h-full shadow-xl">
            <button type="button" aria-label="Close menu" className="absolute -right-9 top-3 text-white" onClick={() => setOpen(false)}><X className="h-6 w-6" /></button>
            <SidebarBody onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
