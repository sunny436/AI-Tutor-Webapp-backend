import { Leaf } from "lucide-react";
import { ThemeSwitcher } from "@/components/theme-switcher";

/**
 * Onboarding shell.
 *
 * Three starter leftovers removed:
 *
 * 1. `<Image src="/logo.png" />` — that file is the Convex v1 starter's black
 *    sphere with "v1" written on it. It was the largest, most prominent element
 *    on the first screen a new user sees after signing up.
 * 2. `base-grid` — a class defined nowhere in the codebase, so this rendered a
 *    fixed, full-screen, 40%-opacity empty div over the page.
 * 3. `h-screen` on three elements plus `w-screen` on two: the mobile-viewport
 *    bug, and a guaranteed horizontal scrollbar on desktop.
 */
export default async function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-dvh w-full flex-col bg-background">
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />

      <header className="relative flex items-center justify-between px-4 py-5 sm:px-6">
        <span className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-brand-foreground"
          >
            <Leaf className="h-[18px] w-[18px]" />
          </span>
          <span className="leading-tight">
            <span className="block font-display text-sm font-semibold text-foreground">
              Ayurveda
            </span>
            <span className="block text-2xs text-text-secondary">by Ollasoftware</span>
          </span>
        </span>
        <ThemeSwitcher />
      </header>

      {/* The third page that had no main landmark. The header above carries the
          brand and the theme switcher; the form is the content, so it is what
          the skip link should land on. */}
      <main id="main" className="relative flex flex-1 items-center justify-center px-4 pb-16">
        {children}
      </main>
    </div>
  );
}
