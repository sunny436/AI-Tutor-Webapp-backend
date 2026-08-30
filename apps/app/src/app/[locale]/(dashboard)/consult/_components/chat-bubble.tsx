"use client";

import { Leaf } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The two shapes a consultation turn can take.
 *
 * WHY THESE ARE HERE AND NOT IN `packages/ui`
 *
 * They are used by exactly one screen. A shared package earns a component when
 * three screens need it; moving a single-use component there buys an import
 * path and a second file to keep in step, and it would put `lucide-react` and
 * this product's leaf mark into a package that is meant to be product-neutral.
 * `_components/` beside the page is where the rest of this route's parts live.
 *
 * Extracted from `page.tsx` all the same, because that file is a thousand lines
 * and the turn markup was buried mid-render — which is most of why the two
 * bubbles had drifted into being styled by different rules.
 *
 * THE ASYMMETRY IS THE POINT. A consultation is not two people texting. What
 * the reader says is a short aside; what the assistant says is the document
 * they came for. So the user's turn is a contained bubble that shrink-wraps its
 * text, and the assistant's is the full reading column with no bubble around it
 * at all. Giving them matching treatments is what makes a health product read
 * as a chat toy.
 */

/**
 * What the reader said.
 *
 * `break-words` is not decoration: a pasted URL or one long unbroken word would
 * otherwise widen the bubble past the viewport and give the whole page a
 * horizontal scrollbar.
 *
 * `rounded-2xl` with a squared-off bottom-right — the tail. Per the radius
 * scale in `globals.css`, 2xl is reserved for exactly this: chat bubbles are
 * the one place a soft spoken shape is wanted, and keeping it here is what
 * stops it leaking onto cards.
 */
export function UserBubble({ children }: { children: ReactNode }) {
  return (
    <div className="ml-auto max-w-[85%] animate-rise-in whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[0.9375rem] font-medium leading-relaxed text-brand-foreground elev-2 sm:max-w-[78%]">
      {children}
    </div>
  );
}

/**
 * What the assistant said — the reading column.
 *
 * No max-width here on purpose. The assistant's turn is constrained by the
 * page, not by a bubble; capping it left a ragged right edge that made long
 * plans look like chat messages rather than written guidance.
 */
export function AssistantBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex animate-rise-in gap-3">
      {/* `bg-brand`, not an emerald→teal gradient. The app once had eight
          hand-rolled copies of that gradient competing with the token-driven
          <Button> on the same screens — two primary treatments, neither of them
          the design system's. */}
      <span
        aria-hidden
        className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand text-brand-foreground elev-1"
      >
        <Leaf className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/**
 * The card the assistant's prose sits on.
 *
 * Separate from `AssistantBubble` because the streaming placeholder, a chat
 * reply, an escalation and a finished plan all want the same sheet but
 * different contents — and the loader wants the sheet with no content at all.
 */
export function AssistantSheet({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl rounded-tl-md border border-border bg-card p-4 elev-1 ${className}`}
    >
      {children}
    </div>
  );
}
