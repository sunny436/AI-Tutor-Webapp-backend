import { Sparkles } from "lucide-react";

import { APP_NAME } from "@/lib/brand";

/** What a new, empty chat shows. */
export function ChatEmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
      <span aria-hidden className="mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-brand-soft text-brand">
        <Sparkles className="h-6 w-6" />
      </span>
      <h2 className="font-display text-2xl font-semibold tracking-tight text-foreground">How can I help?</h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
        Ask {APP_NAME} anything — to explain, write, summarise or debug.
      </p>
    </div>
  );
}
