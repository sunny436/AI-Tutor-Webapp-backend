/**
 * Two outside checks, with timeouts and this app's failure rules (protection.test.ts):
 *
 * - passwordBreached: Have I Been Pwned's range API (k-anonymity). Only the first five characters
 *   of the password's SHA-1 leave the server, and the answer is padded, so neither the password
 *   nor whether it matched can be read off the wire. A password seen in a breach is refused. If
 *   the service does not answer, the caller refuses as well (fails closed): nobody is locked out
 *   meanwhile, since an email code still signs in.
 * - turnstileOk: Cloudflare Turnstile's siteverify, server side, for the CAPTCHA the sign-in form
 *   shows once the attempt counters say an address or a network is being hammered (config.ts).
 *   A token is single-use and only Cloudflare can say whether it is good.
 */

import { createHash } from "node:crypto";

const HIBP_RANGE = "https://api.pwnedpasswords.com/range/";
const SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const TIMEOUT_MS = 5000;

/** True when the password appears in Have I Been Pwned. Throws when the service can't answer. */
export async function passwordBreached(password: string, fetchImpl: typeof fetch = fetch): Promise<boolean> {
  const sha1 = createHash("sha1").update(password, "utf8").digest("hex").toUpperCase();
  const response = await fetchImpl(`${HIBP_RANGE}${sha1.slice(0, 5)}`, {
    headers: { "Add-Padding": "true", "User-Agent": "PadhAI-password-check" },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`pwnedpasswords answered ${response.status}`);
  const suffix = sha1.slice(5);
  for (const line of (await response.text()).split("\n")) {
    const [hash, count] = line.trim().split(":");
    // Padding lines are made-up suffixes with a count of 0.
    if (hash?.toUpperCase() === suffix) return Number(count) > 0;
  }
  return false;
}

/** Whether Cloudflare accepts this Turnstile token. Throws when Cloudflare can't answer. */
export async function turnstileOk(
  token: string,
  secret: string,
  remoteIp: string | null,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  if (!token || token.length > 2048) return false;
  const body = new URLSearchParams({ secret, response: token });
  if (remoteIp) body.set("remoteip", remoteIp);
  const response = await fetchImpl(SITEVERIFY, { method: "POST", body, signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!response.ok) throw new Error(`siteverify answered ${response.status}`);
  return ((await response.json()) as { success?: unknown }).success === true;
}
