import "server-only";

import { createAuth, readAuthEnv } from "./config";

/**
 * Better Auth for this process, built on first use, never at import: `next build` imports route
 * modules and must not need the database or any secret.
 */
let built: ReturnType<typeof createAuth> | null = null;

export function getAuth(): ReturnType<typeof createAuth> {
  built ??= createAuth(readAuthEnv());
  return built;
}

/**
 * Whether sign-in works here (for /api/health and the deploy smoke): Better Auth started (its
 * schema check passed; otherwise every /api/auth request fails) and the identity tables answer.
 */
export async function authDatabaseOk(timeoutMs = 3000): Promise<boolean> {
  try {
    const { auth, pool } = getAuth();
    const ready = Promise.all([auth.$context, pool.query("SELECT 1 FROM auth_accounts LIMIT 1")]);
    const timeout = new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timeout")), timeoutMs));
    await Promise.race([ready, timeout]);
    return true;
  } catch {
    return false;
  }
}
