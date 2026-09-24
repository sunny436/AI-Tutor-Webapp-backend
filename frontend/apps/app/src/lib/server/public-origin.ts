/**
 * The origin the BROWSER used, which is not always what the server sees.
 *
 * In production the app runs behind a Cloudflare Tunnel: TLS ends at the edge and
 * Next.js is reached over plain HTTP on loopback. `request.url` then says
 * `http://localhost:3000`, which is wrong for three things this app must get right:
 *
 *   - redirects      (a Location of https://localhost:3000/... is a dead address)
 *   - the CSRF check (the browser's `Origin` is the public hostname)
 *   - cookies        (Secure + the `__Host-` prefix only when the browser is on HTTPS)
 *
 * The forwarded headers are trustworthy here because the app binds to 127.0.0.1
 * and only the tunnel can reach it. Pure functions over headers, so middleware
 * (edge runtime) and route handlers (node) share them.
 */

type HeaderSource = { get(name: string): string | null };

function firstValue(value: string | null): string | null {
  const first = value?.split(",")[0]?.trim();
  return first || null;
}

export function publicProtocol(headers: HeaderSource, requestUrl: string): "http" | "https" {
  const forwarded = firstValue(headers.get("x-forwarded-proto"));
  if (forwarded === "https" || forwarded === "http") return forwarded;
  return new URL(requestUrl).protocol === "https:" ? "https" : "http";
}

export function publicHost(headers: HeaderSource, requestUrl: string): string {
  return firstValue(headers.get("x-forwarded-host")) ?? headers.get("host") ?? new URL(requestUrl).host;
}

/** e.g. `https://chat.example.com` */
export function publicOrigin(headers: HeaderSource, requestUrl: string): string {
  return `${publicProtocol(headers, requestUrl)}://${publicHost(headers, requestUrl)}`;
}

/** An absolute URL on the public origin, for redirects. */
export function publicUrlFor(headers: HeaderSource, requestUrl: string, pathAndQuery: string): URL {
  return new URL(pathAndQuery, publicOrigin(headers, requestUrl));
}
