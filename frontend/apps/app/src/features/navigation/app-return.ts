/**
 * Where "Close settings" goes: the last page of the main app this tab showed.
 *
 * Kept in sessionStorage, which is per tab (two tabs never mix; a duplicated tab starts from its
 * original's page) and is UI state only: it never reaches the API. Every value goes through
 * `safeRedirect` on the way in and out, so a stale, hand-edited or hostile entry can only ever
 * resolve to a page of this app, never to Settings itself, the auth pages, the API or another
 * site. Anything unusable, including storage that is missing or throws, means "/".
 */

import { safeRedirect } from "@/lib/safe-redirect";

export const APP_RETURN_KEY = "padhai.appReturnPath";
const CHANGED = "padhai:app-return";
const HOME = "/";

type Store = Pick<Storage, "getItem" | "setItem">;

function acceptable(path: string | null | undefined): string | null {
  const safe = safeRedirect(path, "");
  if (!safe) return null;
  const pathname = safe.split(/[?#]/, 1)[0] ?? "";
  if (pathname === "/settings" || pathname.startsWith("/settings/") || pathname === "/unsubscribe") return null;
  return safe;
}

export function createAppReturn(store: () => Store | null, changed: () => void = () => undefined) {
  const read = (): string | null => {
    try {
      return store()?.getItem(APP_RETURN_KEY) ?? null;
    } catch {
      return null;
    }
  };
  const write = (value: string) => {
    try {
      store()?.setItem(APP_RETURN_KEY, value);
    } catch {
      // storage full or blocked: "Close settings" falls back to the home page
    }
    changed();
  };
  return {
    /** Called by the app shell on every page it shows. */
    remember(path: string): void {
      const safe = acceptable(path);
      if (safe) write(safe);
    },
    /** Where to go back to; "/" when there is nothing usable. */
    get(): string {
      return acceptable(read()) ?? HOME;
    },
    /** The page remembered is now known by another address (a new chat got its id). */
    retarget(from: string, to: string): void {
      if (read() === from) this.remember(to);
    },
    /** The page remembered no longer exists (its chat was deleted). */
    forget(path: string): void {
      if (read() === path) write(HOME);
    },
  };
}

const appReturn = createAppReturn(
  () => (typeof window === "undefined" ? null : window.sessionStorage),
  () => window.dispatchEvent(new Event(CHANGED)),
);

/** For useSyncExternalStore: the page can change while Settings is open (a new chat's address). */
export function subscribeAppReturn(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  return () => window.removeEventListener(CHANGED, onChange);
}

export const rememberAppPath = (path: string) => appReturn.remember(path);
export const appReturnPath = () => appReturn.get();
export const retargetAppPath = (from: string, to: string) => appReturn.retarget(from, to);
export const forgetAppPath = (path: string) => appReturn.forget(path);
