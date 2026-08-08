/**
 * Canonical email handling for auth.
 *
 * Convex Auth uses whatever string the form sent as the account's
 * `providerAccountId` (see `Password`'s `profile` option, which we override in
 * `auth.ts`). Without normalisation, signing up as `Foo@Example.com` and later
 * signing in as `foo@example.com` looks like two different accounts and fails
 * with `InvalidAccountId`. Every path that touches an account id — the provider
 * config and the pre-flight checks in `authStatus.ts` — must agree, so the rule
 * lives here.
 */

/** Lowercase + trim, so one address is always one account. */
export function normalizeEmail(email: unknown): string {
  return String(email ?? "").trim().toLowerCase();
}

/**
 * Deliberately permissive: the browser already applies `type="email"`, and the
 * only thing the server truly needs to reject is a value that cannot address an
 * email at all. Over-strict server-side regexes reject valid real-world addresses.
 */
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 254;
}
