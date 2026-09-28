import { Button } from "@v1/ui/button";

import { BrandMark } from "@/components/brand/brand-mark";

/**
 * The API could not be reached while loading the app. Shown instead of signing
 * the user out: an outage is not a lost session (the old app conflated the two).
 */
export function ServiceUnavailable() {
  return (
    <main
      id="main"
      tabIndex={-1}
      role="alert"
      className="relative flex min-h-dvh w-full flex-col items-center justify-center gap-4 bg-background px-6 py-10 text-center outline-none"
    >
      <div aria-hidden className="backdrop-wash pointer-events-none fixed inset-0" />
      <div className="relative">
        <BrandMark size={56} className="mx-auto mb-5 rounded-2xl" />
        <h1 className="font-display text-2xl font-black tracking-tight text-foreground">We can't reach the service</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          The chat service is temporarily unavailable. Your chats are safe — please try again in a moment.
        </p>
        <div className="mt-6 flex justify-center">
          {/* A plain link: a full reload re-runs the server check. */}
          <Button asChild>
            <a href="/">Try again</a>
          </Button>
        </div>
      </div>
    </main>
  );
}
