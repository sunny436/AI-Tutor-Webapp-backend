"use client";

import { Button } from "@v1/ui/button";
import Link from "next/link";
import { useEffect } from "react";

import { BrandMark } from "@/components/brand/brand-mark";
import { ThemeSwitcher } from "@/components/theme-switcher";

/**
 * A page failed to render; the app shell is fine. No digest, stack or status
 * code: the reader needs a way forward, and the exception is in the console and
 * (when configured) Sentry. `min-h-dvh`, not `h-screen`, so the buttons are never
 * trapped under a mobile browser's toolbar.
 */
export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main
      id="main"
      tabIndex={-1}
      role="alert"
      className="relative flex min-h-dvh w-full flex-col items-center justify-center gap-4 bg-background px-6 py-10 text-center outline-none"
    >
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div className="absolute right-4 top-4">
        <ThemeSwitcher />
      </div>
      <div className="relative">
        <BrandMark size={56} className="mx-auto mb-5 rounded-2xl" />
        <h1 className="font-display text-2xl font-black tracking-tight text-foreground">Something went wrong</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          This page could not be loaded. Your chats are saved and nothing has been lost.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button onClick={() => reset()}>Try again</Button>
          <Button asChild variant="outline">
            <Link href="/">Go to chats</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
