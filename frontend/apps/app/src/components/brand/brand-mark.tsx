import { cn } from "@v1/ui/utils";

import { BRAND } from "@/lib/brand";

/**
 * The logo mark, from the one brand asset (see lib/brand.ts). Decorative: every
 * place it appears names the product in text as well, so it carries no alt text.
 */
export function BrandMark({ size = 40, className }: { size?: number; className?: string }) {
  return (
    <img
      src={BRAND.markSrc}
      alt=""
      aria-hidden
      width={size}
      height={size}
      draggable={false}
      // Explicit size: Tailwind's base sets `img { height: auto }`, and in a
      // stretching flex row the image then grew to the row's height.
      style={{ width: size, height: size }}
      className={cn("shrink-0 select-none", className)}
    />
  );
}

/** "Padh" + "AI", the second part in the brand colour. */
export function BrandWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-display font-black tracking-tight text-foreground", className)}>
      {BRAND.wordmark.lead}
      <span className="text-brand">{BRAND.wordmark.accent}</span>
    </span>
  );
}

/** Mark, wordmark and tagline: the lockup at the top of the sidebar and on sign-in. */
export function BrandLockup({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <span className={cn("flex items-center gap-3", className)}>
      <BrandMark size={compact ? 36 : 44} className="rounded-2xl shadow-md shadow-brand/20" />
      <span className="flex min-w-0 flex-col items-start gap-1">
        <BrandWordmark className={compact ? "text-xl leading-none" : "text-2xl leading-none"} />
        <span className="rounded-full border border-brand/15 bg-brand-soft px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-brand">
          {BRAND.tagline}
        </span>
      </span>
    </span>
  );
}
