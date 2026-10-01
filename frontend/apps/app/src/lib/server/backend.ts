/**
 * Server-side reads from the API, for server components (layouts, auth pages).
 *
 * The result is a three-way outcome on purpose. The old app treated "the backend
 * is unreachable" as "signed out", so an outage bounced everyone to the login
 * page. Here an outage is reported as an outage, and only a real 401 means the
 * session is over.
 */

export type BackendResult<T> =
  | { status: "ok"; data: T }
  | { status: "unauthorized" }
  | { status: "not_found" }
  | { status: "unavailable" };

export async function backendGet<T>(
  apiBaseUrl: string,
  path: string,
  token: string | null,
  options: { fetchImpl?: typeof fetch; timeoutMs?: number; requestId?: string } = {},
): Promise<BackendResult<T>> {
  if (!token) return { status: "unauthorized" };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 10_000);
  try {
    const response = await (options.fetchImpl ?? fetch)(`${apiBaseUrl}${path}`, {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        "X-Request-ID": options.requestId ?? crypto.randomUUID().replace(/-/g, ""),
      },
      cache: "no-store",
      signal: controller.signal,
    });
    // 403 is a session the API will not use (an unverified address): signed out, not an outage.
    if (response.status === 401 || response.status === 403) return { status: "unauthorized" };
    if (response.status === 404) return { status: "not_found" };
    if (!response.ok) return { status: "unavailable" };
    return { status: "ok", data: (await response.json()) as T };
  } catch {
    return { status: "unavailable" };
  } finally {
    clearTimeout(timer);
  }
}
