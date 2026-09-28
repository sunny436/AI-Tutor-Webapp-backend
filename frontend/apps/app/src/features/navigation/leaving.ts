/**
 * Where the student is on their way to, while Next is still loading it.
 *
 * A signal, not routing: it never navigates, never blocks, never cancels. Its only reader is the
 * chat (chat-context.tsx): a new chat that gets its id while the student is already leaving must
 * not give itself its URL, because that `router.replace` would overtake the navigation in flight
 * (Next keeps the newest navigation), and the student would land back in the chat.
 *
 * Fed by a passive, bubble-phase click listener (NavigationGuardRoot) — so a click the unsaved-
 * changes guard stopped in the capture phase never counts — and cleared the moment a navigation
 * commits (the pathname changes) or history moves. The latest click wins: a link back to the page
 * already shown means "staying".
 */

type ClickLike = {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  target: EventTarget | null;
};

export function createLeavingTracker() {
  let leavingTo: string | null = null;

  return {
    /** The pathname a navigation in flight is heading to, or null. */
    current(): string | null {
      return leavingTo;
    },

    click(event: ClickLike, here: URL): void {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      if (!anchor || !("href" in anchor)) return;
      const link = anchor as HTMLAnchorElement;
      if (link.target === "_blank" || link.hasAttribute("download")) return;
      const to = new URL(link.href, here.href);
      if (to.origin !== here.origin) return; // leaving the app: the page unloads
      leavingTo = to.pathname === here.pathname ? null : to.pathname;
    },

    /** A navigation committed, or history moved: nothing is in flight any more. */
    settled(): void {
      leavingTo = null;
    },
  };
}

/** The one tracker of this page load. */
export const leaving = createLeavingTracker();
