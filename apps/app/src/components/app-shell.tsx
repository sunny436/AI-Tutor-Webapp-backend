"use client";

import { Sheet, SheetContent, SheetTitle } from "@v1/ui/sheet";
import { Menu, SquarePen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { useConversations } from "@/features/chat/chat-context";
import { SidebarContent, activeConversationId, useCollapsedSidebar } from "./sidebar";

/**
 * Sidebar | (top bar + page). A flex layout the height of the dynamic viewport,
 * so the chat's composer sits at the bottom on every breakpoint without the old
 * hand-maintained `calc(100dvh - chrome)` arithmetic.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { collapsed, toggle } = useCollapsedSidebar();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-background">
      {/* Desktop rail. Not rendered below md (the drawer below is the only copy there). */}
      <aside className="hidden h-full shrink-0 md:block">
        <SidebarContent collapsed={collapsed} onToggleCollapse={toggle} />
      </aside>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" aria-describedby={undefined} className="md:hidden">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SidebarContent onNavigate={() => setMenuOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setMenuOpen(true)} />
        <main id="main" className="min-h-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}

function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const pathname = usePathname();
  const { items } = useConversations();
  const active = activeConversationId(pathname);
  const title =
    pathname === "/settings"
      ? "Settings"
      : active
        ? (items.find((item) => item.id === active)?.title ?? "Chat")
        : "New chat";

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-2 sm:px-4">
      <button
        type="button"
        onClick={onOpenMenu}
        aria-label="Open menu"
        className="focus-ring grid h-10 w-10 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground md:hidden"
      >
        <Menu aria-hidden className="h-5 w-5" />
      </button>
      <h1 className="min-w-0 flex-1 truncate px-1 text-sm font-medium text-foreground">{title}</h1>
      <Link
        href="/"
        aria-label="New chat"
        className="focus-ring grid h-10 w-10 place-items-center rounded-lg text-text-secondary transition-colors hover:bg-surface-2 hover:text-foreground md:hidden"
      >
        <SquarePen aria-hidden className="h-5 w-5" />
      </Link>
    </header>
  );
}
