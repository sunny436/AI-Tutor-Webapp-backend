/**
 * Server-only configuration.
 *
 * `API_BASE_URL` is where the chat API listens. It is NOT a `NEXT_PUBLIC_` value:
 * browsers never call the API, so its address never needs to reach them. The
 * default is the address the API binds to by contract (`127.0.0.1:4000`), so the
 * app builds and runs without any configuration next to a local API.
 */

export const DEFAULT_API_BASE_URL = "http://127.0.0.1:4000";

export function apiBaseUrl(env: Record<string, string | undefined> = process.env): string {
  const raw = env.API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  const url = new URL(raw);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("API_BASE_URL must be an http(s) URL");
  }
  return raw.replace(/\/+$/, "");
}

/**
 * The secret Better Auth signs its session cookie with (web.env BETTER_AUTH_SECRET): the BFF and
 * server components verify the signature before using a token. Empty = no session is accepted.
 */
export function authSecret(env: Record<string, string | undefined> = process.env): string {
  return env.BETTER_AUTH_SECRET?.trim() ?? "";
}
