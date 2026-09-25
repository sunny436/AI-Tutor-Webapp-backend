import { cn } from "@v1/ui/utils";
import type { ReactNode } from "react";

import { PreviewBadge } from "@/components/preview-badge";

const WIDTHS = { narrow: "max-w-3xl", default: "max-w-4xl", wide: "max-w-6xl" } as const;

/**
 * The frame of a learning-tool page: its own scroll area (the shell does not
 * scroll), a measure, and — first, above everything — the notice that what
 * follows is sample data. These pages exist only with preview features on
 * (lib/preview.ts); the notice is what keeps even a preview honest.
 */
export function ToolPage({
  width = "default",
  className,
  children,
}: {
  width?: keyof typeof WIDTHS;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className="scrollbar-subtle h-full overflow-y-auto">
      <div className={cn("mx-auto flex w-full flex-col gap-6 px-4 py-6 sm:px-6", WIDTHS[width], className)}>
        <p
          role="note"
          className="flex items-start gap-2 self-stretch rounded-xl border border-warning/30 bg-warning-soft px-3 py-2 text-xs font-medium text-warning"
        >
          <PreviewBadge className="mt-px" />
          <span>Sample data, not connected yet: this is a preview of a feature that is coming.</span>
        </p>
        {children}
      </div>
    </div>
  );
}

/** A control whose feature does not exist yet: disabled, with "Soon" beside its label. */
export function SoonLabel({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <PreviewBadge label="Soon" />
    </>
  );
}
