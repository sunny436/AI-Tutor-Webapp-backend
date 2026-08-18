"use client";

import { Button } from "@v1/ui/button";
import Link from "next/link";
import { useEffect } from "react";
import { ThemeSwitcher } from "@/components/theme-switcher";

/**
 * The route-level error boundary — a page failed, but the app shell is fine.
 * (`app/global-error.tsx` is the harsher case where the root layout itself
 * failed, and has to supply its own <html> and inline styles.)
 *
 * Same viewport fix as the 404: `h-screen w-screen` was a fixed height set to
 * the toolbar-hidden mobile viewport, so the recovery buttons could end up below
 * the fold with no way to scroll to them — on the one screen whose entire job is
 * to offer a way out.
 */
export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div
      role="alert"
      className="relative flex min-h-dvh w-full flex-col items-center justify-center gap-4 bg-background px-6 py-10 text-center"
    >
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div className="absolute right-4 top-4">
        <ThemeSwitcher />
      </div>

      <div className="relative">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">
          Something went wrong
        </h1>
        {/* No digest, no stack, no status code. The person reading this wants a
            way forward; the exception is already in the console and in Sentry,
            where it is actually useful. */}
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          This page could not be loaded. Your consultations are saved and nothing
          has been lost.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button onClick={() => reset()}>Try again</Button>
          <Button asChild variant="outline">
            <Link href="/">Go home</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
