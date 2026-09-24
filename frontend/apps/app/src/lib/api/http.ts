/**
 * The one way the browser calls the API: same-origin, through the BFF.
 *
 * The browser never holds a token and never talks to the backend host. It calls
 * `/api/v1/...`; the Next.js server attaches the session from its httpOnly cookie
 * and forwards the request (see `lib/server/proxy-core.ts`).
 */

import { ApiError, errorFromResponse, isAbortError } from "./errors";
import { type RouteKey, type RouteParams, buildPath, splitRouteKey } from "./routes";

/** The BFF mount point: `/api` + the backend path (`/v1/...`). */
export const BFF_PREFIX = "/api";

type Listener = (error: ApiError) => void;
const unauthorizedListeners = new Set<Listener>();

/**
 * Called whenever the API reports that the session is gone (401 `unauthorized`).
 * The app shell subscribes and sends the user to sign in. Returns an unsubscribe.
 */
export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

export function notifyUnauthorized(error: ApiError): void {
  if (error.code !== "unauthorized") return;
  for (const listener of unauthorizedListeners) listener(error);
}

export type CallOptions = {
  params?: RouteParams;
  query?: Record<string, string | number | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
  /** Test seam; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
};

export function urlFor(key: RouteKey, options: Pick<CallOptions, "params" | "query"> = {}): string {
  const path = `${BFF_PREFIX}${buildPath(key, options.params)}`;
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== "") search.set(name, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

/**
 * Call a JSON route. Resolves with the parsed body (`undefined` for 202/204 with
 * no body). Rejects with `ApiError` — including `network_error` when the server
 * could not be reached — or rethrows an `AbortError` untouched.
 */
export async function callRoute<T>(key: RouteKey, options: CallOptions = {}): Promise<T> {
  const { method } = splitRouteKey(key);
  const fetcher = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetcher(urlFor(key, options), {
      method,
      headers:
        options.body === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, "network_error");
  }

  if (!response.ok) {
    const error = await errorFromResponse(response);
    notifyUnauthorized(error);
    throw error;
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, "internal_error");
  }
}
