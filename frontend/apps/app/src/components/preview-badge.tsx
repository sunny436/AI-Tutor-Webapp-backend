import { cn } from "@v1/ui/utils";

/**
 * Says on screen that what sits beside it is not real yet: "Preview" on sample
 * data, "Soon" on a control that does nothing yet. Only ever rendered with
 * preview features on (lib/preview.ts), so production never shows it — and
 * never shows what it labels.
 */
export function PreviewBadge({ label = "Preview", className }: { label?: "Preview" | "Soon"; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border border-warning/30 bg-warning-soft px-1.5 py-px text-[0.625rem] font-bold uppercase leading-4 tracking-wide text-warning",
        className,
      )}
    >
      {label}
    </span>
  );
}
