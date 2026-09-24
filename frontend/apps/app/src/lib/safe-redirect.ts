/**
 * Where to send someone after signing in — only ever somewhere inside this app.
 *
 * The previous check (`startsWith("/") && !startsWith("//")`) let `/\evil.com`
 * through: browsers treat a backslash as a slash in URLs, so that is a
 * protocol-relative link to another site. This rejects:
 *
 *   - anything not starting with a single "/"          (`https://x`, `javascript:`, `x`)
 *   - `//`, and any backslash, raw or percent-encoded
 *   - control characters (tab/newline tricks)
 *   - anything that resolves to a different origin
 *   - the API and the auth pages themselves           (no loops, no JSON pages)
 */

const BASE = "https://app.invalid";

function hasControlCharacter(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 0x20 || code === 0x7f) return true;
  }
  return false;
}

function unsafe(value: string): boolean {
  return value.startsWith("//") || value.includes("\\") || hasControlCharacter(value);
}

export function safeRedirect(target: string | null | undefined, fallback = "/"): string {
  if (!target || target.length > 2048 || !target.startsWith("/")) return fallback;
  if (unsafe(target)) return fallback;

  let decoded: string;
  try {
    decoded = decodeURIComponent(target);
  } catch {
    return fallback;
  }
  if (unsafe(decoded)) return fallback;

  let url: URL;
  try {
    url = new URL(target, BASE);
  } catch {
    return fallback;
  }
  if (url.origin !== BASE) return fallback;

  const path = url.pathname;
  if (path === "/api" || path.startsWith("/api/")) return fallback;
  if (path === "/login" || path === "/signup") return fallback;

  return `${path}${url.search}${url.hash}`;
}
