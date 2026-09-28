import { Button } from "@v1/ui/button";
import Link from "next/link";

import { BrandMark } from "@/components/brand/brand-mark";
import { ThemeSwitcher } from "@/components/theme-switcher";

export const metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <main
      id="main"
      tabIndex={-1}
      className="relative flex min-h-dvh w-full flex-col items-center justify-center gap-4 bg-background px-6 py-10 text-center outline-none"
    >
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div className="absolute right-4 top-4">
        <ThemeSwitcher />
      </div>
      <div className="relative">
        <BrandMark size={56} className="mx-auto mb-5 rounded-2xl" />
        <p className="text-sm font-bold uppercase tracking-widest text-brand">404</p>
        <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-foreground">
          This page could not be found
        </h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          The link may be out of date, or the page may have moved.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button asChild>
            <Link href="/">Start a new chat</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
