/**
 * Per-account limits for Better Auth, in the API's own table (auth_attempts) with the API's
 * scopes and keys (backend/app/auth/service.py `_throttle`): SHA-256 of the lower-cased email,
 * counted under a transaction-scoped advisory lock on `scope|hash`. The lock makes
 * count-then-insert atomic across both runtimes, so a burst of parallel requests can never pass
 * more attempts than the limit. A refused attempt is not recorded: the limit lifts once the
 * window passes.
 *
 * Better Auth's own limiter (per IP, in memory) runs first; these hold per account whatever the
 * number of addresses an attacker uses.
 */

import { createHash } from "node:crypto";

import type { Pool } from "pg";

export type Limit = { scope: string; max: number; minutes: number };

/** Password checks per account: sign-in and change-password here, re-authentication in the API. */
export const SIGNIN: Limit = { scope: "signin_email", max: 10, minutes: 15 };
/** Code checks per address, across every code sent to it (a resend does not reset this). */
export const CODE_CHECKS: Limit = { scope: "code_check_email", max: 20, minutes: 24 * 60 };
/** Codes sent per address: no mail-bombing anyone from our mailbox. */
export const CODE_SENDS: Limit[] = [
  { scope: "code_send_email", max: 5, minutes: 15 },
  { scope: "code_send_email_day", max: 20, minutes: 24 * 60 },
];

export function keyHash(value: string): string {
  return createHash("sha256").update(value.toLowerCase()).digest("hex");
}

/** Count one attempt and return true, or return false when `max` were made in the window. */
export async function reserve(pool: Pool, limit: Limit, key: string): Promise<boolean> {
  const hash = keyHash(key);
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [`${limit.scope}|${hash}`]);
    const counted = await client.query<{ n: number }>(
      "SELECT count(*)::int AS n FROM auth_attempts " +
        "WHERE scope = $1 AND key_hash = $2 AND created_at > now() - make_interval(mins => $3)",
      [limit.scope, hash, limit.minutes],
    );
    const allowed = (counted.rows[0]?.n ?? 0) < limit.max;
    if (allowed) await client.query("INSERT INTO auth_attempts (scope, key_hash) VALUES ($1, $2)", [limit.scope, hash]);
    await client.query("COMMIT");
    return allowed;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

/**
 * Counters that only decide when the CAPTCHA is asked for (config.ts): attempts per network
 * (CF-Connecting-IP) and code requests per address, recorded whether or not the address has an
 * account, so asking for a CAPTCHA never says which addresses exist.
 */
export const WATCH = {
  signinIp: "signin_ip",
  codeAskEmail: "code_ask_email",
  codeAskIp: "code_ask_ip",
  codeCheckIp: "code_check_ip",
} as const;

export async function record(pool: Pool, scope: string, key: string): Promise<void> {
  await pool.query("INSERT INTO auth_attempts (scope, key_hash) VALUES ($1, $2)", [scope, keyHash(key)]);
}

export async function recent(pool: Pool, scope: string, key: string, minutes: number): Promise<number> {
  const { rows } = await pool.query<{ n: number }>(
    "SELECT count(*)::int AS n FROM auth_attempts " +
      "WHERE scope = $1 AND key_hash = $2 AND created_at > now() - make_interval(mins => $3)",
    [scope, keyHash(key), minutes],
  );
  return rows[0]?.n ?? 0;
}
