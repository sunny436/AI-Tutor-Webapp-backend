/**
 * Unsaved edits are never lost by leaving without being asked, whichever way the student leaves.
 *
 * One registry of dirty forms (so one question per departure, however many forms are dirty) and
 * one set of listeners, installed by <NavigationGuardRoot> in the signed-in layout:
 *
 *   links (category, Close, All settings, links in a section)   capture-phase click, before
 *                                                              Next's <Link> handler
 *   navigations we start ourselves (search's Enter, log out)   `confirmLeave()` first
 *   reload, closing the tab, another site                      `beforeunload` (the browser's own
 *                                                              prompt; its wording can't be set)
 *   the browser's Back/Forward, Android's back button           a sentinel history entry (below)
 *
 * A single-page app can't cancel Back: by the time `popstate` fires the browser has moved. So when
 * the first edit is made, a SENTINEL entry with the same URL is pushed on top of the page (Next
 * 14.2 copies its own state into an external `pushState` and restores the same page, so nothing
 * remounts). Back then lands on the page itself, still showing the edit: we ask, and either push
 * the sentinel again (stay) or go on back (leave). A sentinel left behind by an earlier edit is
 * stepped over in the direction of travel.
 *
 * Not covered: jumping several entries at once from the browser's history menu (it can't be
 * undone without knowing how far it went). The edit is lost then, as in any single-page app.
 */

export const UNSAVED_MESSAGE = "You have unsaved changes. Leave without saving them?";
const SENTINEL = "padhaiGuard";

export type GuardEnv = {
  confirm(message: string): boolean;
  history: {
    readonly state: unknown;
    pushState(data: unknown, unused: string, url?: string | null): void;
    back(): void;
    forward(): void;
  };
  href(): string;
};

function isSentinel(state: unknown): boolean {
  return typeof state === "object" && state !== null && (state as Record<string, unknown>)[SENTINEL] === 1;
}

export function createNavigationGuard() {
  const dirty = new Set<object>();
  let env: GuardEnv | null = null;
  /** A sentinel we pushed is the current history entry, protecting `armedHref`. */
  let armed = false;
  let armedHref = "";
  /** The student already agreed to leave: don't ask again on the way out (unload, the next popstate). */
  let leaving = false;
  /** Where we were before the latest history move, to tell Back from Forward. */
  let lastHref = "";

  const isDirty = () => dirty.size > 0 && !leaving;

  function arm() {
    if (!env || armed) return;
    armedHref = env.href();
    armed = true;
    env.history.pushState({ [SENTINEL]: 1 }, "", armedHref);
  }

  return {
    isDirty,

    /** A form reports whether it holds edits that aren't saved. */
    setDirty(source: object, value: boolean): void {
      const wasClean = dirty.size === 0;
      if (value) dirty.add(source);
      else dirty.delete(source);
      if (value && wasClean) {
        leaving = false;
        arm();
      }
    },

    /** Before a navigation we start ourselves: true to go ahead. */
    confirmLeave(): boolean {
      if (!isDirty() || !env) return true;
      const ok = env.confirm(UNSAVED_MESSAGE);
      if (ok) leaving = true;
      return ok;
    },

    /** A departure the student agreed to didn't happen after all (log out failed): protect again. */
    stay(): void {
      leaving = false;
    },

    attach(next: GuardEnv): void {
      env = next;
      lastHref = next.href();
      armed = false;
      if (isDirty()) arm();
    },

    detach(): void {
      env = null;
      armed = false;
    },

    /** Next moved to another page (a link, push or replace): any sentinel is now behind us. */
    navigated(href: string): void {
      if (armed && href !== armedHref) armed = false;
      lastHref = href;
    },

    /** The browser moved through history (Back, Forward, the back button). */
    popstate(state: unknown): void {
      if (!env) return;
      const href = env.href();
      const from = lastHref;
      lastHref = href;

      if (armed && href === armedHref && !isSentinel(state)) {
        // Back from our sentinel onto the page it protects: the edit is still on screen.
        armed = false;
        if (isDirty()) {
          if (!env.confirm(UNSAVED_MESSAGE)) {
            arm(); // stay, still protected
            return;
          }
          leaving = true;
        }
        env.history.back(); // on to where the student was going
        return;
      }
      if (armed) armed = false; // several entries at once (the history menu): nothing to undo with

      if (isSentinel(state)) {
        // A sentinel left behind by an earlier edit: step over it.
        if (from === href) env.history.forward();
        else env.history.back();
      }
    },
  };
}

/** The one guard of this page load. */
export const navigationGuard = createNavigationGuard();
