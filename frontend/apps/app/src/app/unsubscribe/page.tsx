import type { Metadata } from "next";

import { BrandLockup } from "@/components/brand/brand-mark";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { UnsubscribeCard } from "@/features/unsubscribe/unsubscribe-card";

export const metadata: Metadata = {
  title: "Unsubscribe",
  // The token is in this page's address: never send it on to another site.
  referrer: "no-referrer",
};

/**
 * The link at the bottom of a reminder or alert email. Public (lib/server/gate.ts): it works
 * signed in, signed out, or on a device that was never signed in.
 */
export default async function UnsubscribePage(props: { searchParams: Promise<{ token?: string | string[] }> }) {
  const searchParams = await props.searchParams;
  const token = typeof searchParams.token === "string" && searchParams.token ? searchParams.token : null;
  return (
    <div className="relative flex min-h-dvh w-full flex-col bg-background">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <header className="relative flex items-center justify-between gap-3 px-4 py-5 sm:px-6">
        <BrandLockup compact />
        <ThemeSwitcher />
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="relative flex flex-1 items-start justify-center px-4 pb-16 pt-6 outline-none sm:items-center sm:pt-0"
      >
        <div className="w-full max-w-md rounded-3xl border border-border bg-card p-6 elev-2 sm:p-8">
          <UnsubscribeCard token={token} />
        </div>
      </main>
    </div>
  );
}
