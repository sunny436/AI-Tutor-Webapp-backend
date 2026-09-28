import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { BrandLockup } from "@/components/brand/brand-mark";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { getCurrentUser } from "@/lib/server/session";

/**
 * Sign-in and sign-up. A visitor whose session is still valid goes straight to
 * the app — decided here, where the session can actually be checked, rather than
 * in middleware (which only sees that a cookie exists, and bouncing on a stale
 * cookie is how redirect loops happen).
 */
export default async function AuthLayout({ children }: { children: ReactNode }) {
  const session = await getCurrentUser();
  if (session.status === "ok") redirect("/");

  return (
    <div className="relative flex min-h-dvh w-full flex-col bg-background">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <header className="relative flex items-center justify-between gap-3 px-4 py-5 sm:px-6">
        <BrandLockup compact />
        <ThemeSwitcher />
      </header>
      <main id="main" tabIndex={-1} className="relative flex flex-1 items-start justify-center px-4 pb-16 pt-6 sm:items-center sm:pt-0 outline-none">
        <div className="w-full max-w-md rounded-3xl border border-border bg-card p-6 elev-2 sm:p-8">{children}</div>
      </main>
    </div>
  );
}
