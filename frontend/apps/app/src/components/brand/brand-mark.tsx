import { cn } from "@v1/ui/utils";
import { Fragment } from "react";

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

/** The tagline's phrases ("Your Questions." ...): a narrow row wraps between them, never inside one. */
const TAGLINE_PHRASES = BRAND.tagline.split(/(?<=\.)\s+/);

/**
 * Mark, wordmark and tagline: the lockup at the top of the sidebar, the Settings panel and
 * sign-in. The tagline is one line in the sidebar: 188px of text at 10px (195px on Linux, which
 * rounds glyph widths), with 217px free in the 288px rail and 201px in the phone drawer (272px
 * on a 320px screen).
 */
export function BrandLockup({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <BrandMark size={36} className="rounded-2xl" />
      <span className="flex min-w-0 flex-col items-start gap-1">
        <BrandWordmark className={compact ? "text-xl leading-none" : "text-2xl leading-none"} />
        <span className="text-[0.625rem] font-medium leading-snug text-text-secondary">
          {TAGLINE_PHRASES.map((phrase, index) => (
            <Fragment key={phrase}>
              {index > 0 && " "}
              <span className="whitespace-nowrap">{phrase}</span>
            </Fragment>
          ))}
        </span>
      </span>
    </span>
  );
}
