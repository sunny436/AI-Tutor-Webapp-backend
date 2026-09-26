"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { navigationGuard } from "./navigation-guard";

/**
 * Installs the unsaved-changes guard's listeners (navigation-guard.ts), once, in the signed-in
 * layout, so they cover every page and outlive any one form. Renders nothing.
 */
export function NavigationGuardRoot() {
  const pathname = usePathname();

  useEffect(() => {
    navigationGuard.attach({
      confirm: (message) => window.confirm(message),
      history: window.history,
      href: () => window.location.href,
    });

    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!navigationGuard.isDirty()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    // Capture phase, so it runs before Next's <Link> handler and can stop it.
    const click = (event: MouseEvent) => {
      if (!navigationGuard.isDirty()) return;
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      if (!(anchor instanceof HTMLAnchorElement) || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const to = new URL(anchor.href, window.location.href);
      if (to.origin !== window.location.origin || to.pathname === window.location.pathname) return;
      if (!navigationGuard.confirmLeave()) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    const popstate = (event: PopStateEvent) => navigationGuard.popstate(event.state);

    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", click, true);
    window.addEventListener("popstate", popstate);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", click, true);
      window.removeEventListener("popstate", popstate);
      navigationGuard.detach();
    };
  }, []);

  useEffect(() => {
    navigationGuard.navigated(window.location.href);
  }, [pathname]);

  return null;
}
