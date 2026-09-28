/**
 * "The answer is on its way", before the first words arrive: three dots breathing in turn
 * (opacity only, no bounce), and nothing else. Silent to screen readers — the chat's status
 * region announces "Assistant is responding" once. Reduced motion holds them still.
 */
export function StreamingIndicator() {
  return (
    <span aria-hidden data-streaming-dots="" className="inline-flex items-center gap-1 py-2">
      {[0, 160, 320].map((delay) => (
        <span
          key={delay}
          className="h-2 w-2 rounded-full bg-brand/60 animate-soft-pulse"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  );
}

/** The caret shown after streamed text while more is coming. */
export function StreamingCaret() {
  return <span aria-hidden className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-soft-pulse bg-brand" />;
}
