import type { AppNotification } from "@/lib/api/types";

/** Unread milestone notifications not celebrated yet in this tab, oldest first (one toast each). */
export function milestonesToCelebrate(items: AppNotification[], celebrated: ReadonlySet<string>): AppNotification[] {
  return items
    .filter((item) => item.kind === "streak_milestone" && item.readAt === null && !celebrated.has(item.id))
    .reverse();
}

/** "3" .. "9", then "9+": a badge that never grows wider than two characters. */
export function unreadBadge(count: number): string | null {
  if (count <= 0) return null;
  return count > 9 ? "9+" : String(count);
}
