"use client";

import { useEffect } from "react";

/**
 * Keeps an active student signed in. Once per page load it asks Better Auth for the session;
 * when the session is due (once a day) Better Auth extends its expiry and re-sets the cookie
 * together, so the cookie never runs out while the session still runs (lib/auth/config.ts).
 * The answer is not used: it carries no token (lib/auth/routes.ts), and the API decides who
 * is signed in.
 */
export function SessionKeeper() {
  useEffect(() => {
    void fetch("/api/auth/get-session", { credentials: "same-origin", cache: "no-store" }).catch(() => undefined);
  }, []);
  return null;
}
