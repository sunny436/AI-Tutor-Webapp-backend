/** "3" .. "9", then "9+": a badge that never grows wider than two characters. */
export function unreadBadge(count: number): string | null {
  if (count <= 0) return null;
  return count > 9 ? "9+" : String(count);
}
