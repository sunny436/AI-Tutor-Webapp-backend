import { APP_NAME } from "@/lib/brand";

/**
 * "The answer is on its way", before the first token arrives. Silent to screen
 * readers — the chat's status region announces "Assistant is responding" once.
 * The bounce is `motion-safe`, and the global reduced-motion rule stops it too.
 */
export function StreamingIndicator() {
  return (
    <span aria-hidden className="inline-flex items-center gap-2 py-1 text-xs text-text-secondary">
      <span className="inline-flex items-center gap-1">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="h-2 w-2 rounded-full bg-brand motion-safe:animate-bounce"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
      <span className="font-medium">{APP_NAME} is generating an answer…</span>
    </span>
  );
}

/** The caret shown after streamed text while more is coming. */
export function StreamingCaret() {
  return <span aria-hidden className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-soft-pulse bg-brand" />;
}
