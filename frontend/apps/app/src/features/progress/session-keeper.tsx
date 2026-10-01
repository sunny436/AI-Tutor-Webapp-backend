"use client";

import { useEffect } from "react";

/**
 * Keeps an active student signed in. Once per page load it asks Better Auth for the session;
 * when the session is due (once a day) Better Auth extends its expiry and re-sets the cookie
 * together, so the cookie never runs out while the session still runs (lib/auth/config.ts).
 * The answer is not used: it carries no token (lib/auth/routes.ts), and the API decides who
 * is signed in. Its body is still read: behind Cloudflare (compressed, HTTP/3) a response whose
 * body nobody reads stays open in the browser for as long as the page lives.
 */
export function SessionKeeper() {
  useEffect(() => {
    void fetch("/api/auth/get-session", { credentials: "same-origin", cache: "no-store" })
      .then((response) => response.text())
      .catch(() => undefined);
  }, []);
  return null;
}
