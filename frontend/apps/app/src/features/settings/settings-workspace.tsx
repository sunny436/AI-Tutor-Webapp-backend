"use client";

import { cn } from "@v1/ui/utils";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useSyncExternalStore } from "react";

import { ThemeSwitcher } from "@/components/theme-switcher";
import { appReturnPath, subscribeAppReturn } from "@/features/navigation/app-return";
import { navigationGuard } from "@/features/navigation/navigation-guard";
import { arrivingFromAnotherView, focusIfLost, focusLost } from "@/features/navigation/route-focus";
import { cancelHeadingFocus, requestHeadingFocus } from "./heading-focus";
import { SettingsPanel } from "./settings-panel";
import { CloseSettings, WorkspaceContext, iconButton } from "./workspace-context";

/**
 * Settings, as its own workspace (not a page inside the app shell): a panel with the brand,
 * Close, search and the sections; a top bar with the title and the theme; the open section,
 * centred. On a phone, `/settings` is the list of sections and each section is its own screen,
 * with "All settings" to go back up. The app's sidebar and header are not here at all: this
 * layout replaces them (app/(app)/settings/layout.tsx, beside app/(app)/(main)/).
 *
 * Navigation (every path through the unsaved-changes guard, features/navigation/):
 *   Close          the last app page of this tab (app-return.ts), else "/"
 *   All settings   /settings, the list (phone)
 *   Back/Forward   plain history; the list comes back scrolled and focused where it was
 *
 * Focus: arriving from the app, or when what was used to navigate disappears (a phone row, All
 * settings), focus goes to the new view's heading, or back to the row just left; a desktop
 * category click keeps focus on the category. Nothing moves focus on a fresh page load.
 */

const LIST = "/settings";
/** Where the phone list was scrolled, while a section is open (a fresh visit starts at the top). */
let listScroll = 0;

export function SettingsWorkspace({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? LIST;
  const router = useRouter();
  const main = useRef<HTMLElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const previous = useRef<string | null>(null);
  const wantsHeading = useRef(false);
  // "/" on the server and while hydrating; then the remembered page (sessionStorage), kept current.
  const closeHref = useSyncExternalStore(subscribeAppReturn, appReturnPath, () => "/");
  const onList = pathname === LIST;

  const sectionHeading = () => main.current?.querySelector<HTMLElement>("[data-settings-heading]") ?? null;

  /** Focus the open section's heading now, or as soon as it appears (it may be loading). */
  const focusHeading = useCallback(() => {
    const heading = sectionHeading();
    if (heading) heading.focus({ preventScroll: true });
    else requestHeadingFocus();
  }, []);

  // Arriving from the app (the Settings link, the streak card, a help link...).
  // On arrival only.
  useEffect(() => {
    listScroll = 0;
    if (!arrivingFromAnotherView()) return;
    const frame = requestAnimationFrame(() => {
      if (!focusLost()) return;
      if (onList) title.current?.focus({ preventScroll: true });
      else focusHeading();
    });
    return () => {
      cancelAnimationFrame(frame);
      cancelHeadingFocus();
    };
  }, []);

  // Where the phone list was, taken at the moment it is left: a click or tap in it (capture
  // phase, before Next navigates) or search opening a section. Not from scroll events: while
  // the list is swapped for a section the browser clamps and re-fires them (WebKit, notably).
  const listShown = useRef(onList);
  useLayoutEffect(() => {
    listShown.current = onList;
  }, [onList]);
  const rememberList = useCallback(() => {
    if (listShown.current && main.current) listScroll = main.current.scrollTop;
  }, []);
  useEffect(() => {
    const element = main.current;
    if (!element) return;
    element.addEventListener("click", rememberList, true);
    return () => element.removeEventListener("click", rememberList, true);
  }, [rememberList]);

  // Moving between sections and the list, inside the workspace.
  // Once per navigation.
  useEffect(() => {
    const from = previous.current;
    previous.current = pathname;
    if (from === null || from === pathname) return;
    const element = main.current;
    const frame = requestAnimationFrame(() => {
      if (!element) return;
      if (pathname === LIST) {
        element.scrollTop = listScroll;
        const row = element.querySelector<HTMLElement>(`a[href="${from}"]`);
        focusIfLost(row ?? title.current);
        return;
      }
      element.scrollTop = 0; // <main> persists: a new section starts at its top
      if (wantsHeading.current || focusLost()) focusHeading();
      wantsHeading.current = false;
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  const openSection = useCallback(
    (slug: string) => {
      const href = `${LIST}/${slug}`;
      if (href === pathname) {
        focusHeading();
        return true;
      }
      if (!navigationGuard.confirmLeave()) return false;
      rememberList();
      wantsHeading.current = true;
      router.push(href);
      return true;
    },
    [pathname, router, focusHeading, rememberList],
  );

  const workspace = useMemo(() => ({ closeHref, openSection }), [closeHref, openSection]);

  return (
    <WorkspaceContext.Provider value={workspace}>
      <div className="flex h-dvh w-full overflow-hidden bg-background">
        <aside
          aria-label="Settings"
          className="hidden h-full w-64 shrink-0 flex-col border-r border-border bg-card md:flex lg:w-72"
        >
          <SettingsPanel variant="panel" />
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="z-10 flex h-16 shrink-0 items-center gap-2 border-b border-border bg-card/90 px-2 backdrop-blur-md sm:gap-3 sm:px-4 md:px-6">
            {!onList && (
              <Link href={LIST} scroll={false} aria-label="All settings" className={cn(iconButton, "md:hidden")}>
                <ChevronLeft aria-hidden className="h-5 w-5" />
              </Link>
            )}
            <h1
              ref={title}
              tabIndex={-1}
              className={cn(
                "min-w-0 flex-1 truncate text-base font-bold text-foreground outline-none",
                onList && "pl-2 md:pl-0",
              )}
            >
              Settings
            </h1>
            <ThemeSwitcher />
            <CloseSettings href={closeHref} className="md:hidden" />
          </header>
          <main
            id="main"
            ref={main}
            tabIndex={-1}
            className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto overscroll-contain outline-none"
          >
            <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6 md:py-10 lg:px-10">{children}</div>
          </main>
        </div>
      </div>
    </WorkspaceContext.Provider>
  );
}
