/**
 * The "reply is on its way" dots, before the first token arrives. Silent to
 * screen readers — the chat's status region announces "Assistant is responding"
 * once. `animate-soft-pulse` is switched off under prefers-reduced-motion.
 */
export function StreamingIndicator() {
  return (
    <span aria-hidden className="inline-flex items-center gap-1.5 py-2">
      {[0, 200, 400].map((delay) => (
        <span
          key={delay}
          className="h-2 w-2 animate-soft-pulse rounded-full bg-brand"
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
