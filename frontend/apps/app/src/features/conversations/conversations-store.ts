/**
 * The sidebar's list of conversations: newest activity first, paged by cursor.
 *
 * The first page arrives with the page itself (fetched by the server layout), so
 * the sidebar is filled on first paint. After that the list is kept current from
 * what the chat already knows — a new conversation from the stream's `meta`, a
 * new title or activity from `done` — and refetched when the window regains
 * focus, so a chat started in another tab shows up.
 *
 * Rename and delete are optimistic and roll back (with the error rethrown for a
 * toast) when the API refuses. Nothing here swallows a failure.
 *
 * A title renamed in this tab wins over a stream's copy of the conversation, which may have been
 * read just before the rename was saved (the API never names a renamed chat again), until the next
 * refresh brings the server's own titles.
 */

import type { Conversation, ConversationPage } from "@/lib/api/types";

export type ConversationsApi = {
  listConversations: (options: { limit?: number; cursor?: string | null }) => Promise<ConversationPage>;
  renameConversation: (id: string, title: string) => Promise<Conversation>;
};

export type ConversationsState = Readonly<{
  items: readonly Conversation[];
  nextCursor: string | null;
  status: "ready" | "loading" | "error";
  loadingMore: boolean;
}>;

export const PAGE_SIZE = 30;

const byActivity = (a: Conversation, b: Conversation) =>
  b.updatedAt.localeCompare(a.updatedAt) || b.id.localeCompare(a.id);

export class ConversationsStore {
  private state: ConversationsState;
  private readonly listeners = new Set<() => void>();
  private lastRefresh = 0;
  /** Titles set by a rename in this tab, by conversation id. */
  private readonly renamed = new Map<string, string>();

  constructor(
    private readonly api: ConversationsApi,
    initial: ConversationPage | null,
    private readonly now: () => number = () => Date.now(),
  ) {
    this.state = initial
      ? { items: initial.items, nextCursor: initial.nextCursor, status: "ready", loadingMore: false }
      : { items: [], nextCursor: null, status: "loading", loadingMore: false };
    if (initial) this.lastRefresh = now();
  }

  getSnapshot = (): ConversationsState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  find(id: string): Conversation | undefined {
    return this.state.items.find((item) => item.id === id);
  }

  /** Reload the first page. `minIntervalMs` throttles focus-driven refreshes. */
  async refresh(minIntervalMs = 0): Promise<void> {
    if (minIntervalMs && this.now() - this.lastRefresh < minIntervalMs) return;
    this.lastRefresh = this.now();
    try {
      const page = await this.api.listConversations({ limit: PAGE_SIZE });
      for (const item of page.items) this.renamed.delete(item.id);
      // The first page replaces what we had, so renames and deletions made in
      // another tab show up. Pages loaded beyond it ("Load more") are kept.
      const loadedBeyondFirstPage = this.state.items.length > PAGE_SIZE;
      const firstIds = new Set(page.items.map((item) => item.id));
      const rest = loadedBeyondFirstPage ? this.state.items.filter((item) => !firstIds.has(item.id)) : [];
      this.set({
        items: [...page.items, ...rest].sort(byActivity),
        nextCursor: loadedBeyondFirstPage ? this.state.nextCursor : page.nextCursor,
        status: "ready",
      });
    } catch {
      if (this.state.status === "loading") this.set({ status: "error" });
    }
  }

  async loadMore(): Promise<void> {
    if (!this.state.nextCursor || this.state.loadingMore) return;
    this.set({ loadingMore: true });
    try {
      const page = await this.api.listConversations({ limit: PAGE_SIZE, cursor: this.state.nextCursor });
      const known = new Set(this.state.items.map((item) => item.id));
      this.set({
        items: [...this.state.items, ...page.items.filter((item) => !known.has(item.id))],
        nextCursor: page.nextCursor,
        loadingMore: false,
      });
    } catch (error) {
      this.set({ loadingMore: false });
      throw error;
    }
  }

  /** A conversation was created or changed (title, activity): put it in its place. */
  upsert(conversation: Conversation): void {
    const title = this.renamed.get(conversation.id);
    const next = title === undefined ? conversation : { ...conversation, title };
    const others = this.state.items.filter((item) => item.id !== conversation.id);
    this.set({ items: [next, ...others].sort(byActivity) });
  }

  remove(id: string): void {
    if (!this.find(id)) return;
    this.set({ items: this.state.items.filter((item) => item.id !== id) });
  }

  /** Optimistic rename; rolls back and rethrows if the API refuses. */
  async rename(id: string, title: string): Promise<void> {
    const before = this.find(id);
    if (!before) return;
    const trimmed = title.trim();
    if (!trimmed || trimmed === before.title) return;
    const renamedBefore = this.renamed.get(id);
    this.renamed.set(id, trimmed);
    this.set({ items: this.state.items.map((item) => (item.id === id ? { ...item, title: trimmed } : item)) });
    try {
      const saved = await this.api.renameConversation(id, trimmed);
      this.renamed.set(id, saved.title);
      this.set({ items: this.state.items.map((item) => (item.id === id ? saved : item)) });
    } catch (error) {
      if (renamedBefore === undefined) this.renamed.delete(id);
      else this.renamed.set(id, renamedBefore);
      this.set({ items: this.state.items.map((item) => (item.id === id ? before : item)) });
      throw error;
    }
  }

  /** Put back a conversation whose deletion failed. */
  restore(conversation: Conversation): void {
    this.upsert(conversation);
  }

  private set(patch: Partial<ConversationsState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of [...this.listeners]) listener();
  }
}
