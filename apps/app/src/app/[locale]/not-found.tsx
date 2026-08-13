import { Button } from "@v1/ui/button";
import Link from "next/link";
import { ThemeSwitcher } from "@/components/theme-switcher";

export const metadata = { title: "Page not found" };

/**
 * `min-h-dvh w-full`, not `h-screen w-screen`. `vh` is the mobile viewport with
 * the toolbar hidden, so a fixed-height centred layout sat under the browser
 * chrome with no way to scroll to it; `w-screen` ignores the scrollbar gutter
 * and gave desktop a horizontal scrollbar on a page with nothing to scroll.
 * The same pair of bugs was already fixed on the chat and login screens.
 */
export default function NotFound() {
  return (
    <div className="relative flex min-h-dvh w-full flex-col items-center justify-center gap-4 bg-background px-6 py-10 text-center">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div className="absolute right-4 top-4">
        <ThemeSwitcher />
      </div>

      <div className="relative">
        <p className="font-mono text-sm uppercase tracking-widest text-brand">404</p>
        <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight text-foreground">
          This page could not be found
        </h1>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          The link may be out of date, or the page may have moved. Your
          consultations are unaffected.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button asChild>
            <Link href="/">Go home</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/consult">Start a consultation</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
