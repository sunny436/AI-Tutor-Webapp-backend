"use client";

import { Button } from "@v1/ui/button";

/**
 * A section that failed to render. Shown inside the workspace, so the other sections and Close
 * still work; the root error page would replace everything.
 */
export default function SectionError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-2xl border border-border bg-card p-6">
      <h2 className="font-display text-xl font-bold text-foreground">Couldn't show this section</h2>
      <p className="text-sm text-text-secondary">
        Something went wrong while opening it. Your saved settings are safe. Try again, or choose another section.
      </p>
      <Button type="button" variant="outline" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
