import type { ReactNode } from "react";

/**
 * A labelled group of settings cards.
 *
 * WHAT IT FIXES
 *
 * The account page was four cards in a flat column — avatar, username, password,
 * sessions, delete — with no relationship between them stated anywhere. Every
 * card carried an `h2`, so a screen reader heard five sibling headings of equal
 * rank and the page had no structure to navigate by; sighted readers got the
 * same flatness as one undifferentiated stack. `ROADMAP.md` records the
 * complaint as "Settings has only two sections … moving the security cards out
 * of General".
 *
 * Grouping is the fix, not more tabs. Splitting Profile and Security onto their
 * own routes would mean two clicks to change a password and a nav rail longer
 * than the content it indexes; on a page this size the sections fit on one
 * screen and the reader can see everything their account can do at once.
 *
 * HEADING RANKS ARE THE POINT, not the border. The section owns the `h2` and the
 * cards inside step down to `h3`, so the document outline finally matches what
 * the page looks like. That is why `Card`'s `CardTitle` takes an `as` prop.
 *
 * `.rule-printed` for the divider rather than a plain border: it is the rule
 * this design system already draws for separating parts of a reference work —
 * denser at the ends than the middle, so it reads as set type rather than a div
 * edge. It had zero call sites before this.
 */
export function SettingsSection({
  title,
  description,
  children,
  tone = "default",
}: {
  title: string;
  description?: string;
  children: ReactNode;
  /**
   * `danger` tints the heading only. The destructive treatment stays on the
   * card that actually performs the irreversible thing — a whole section
   * painted red reads as "this area is broken" rather than "be careful here".
   */
  tone?: "default" | "danger";
}) {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2
          className={`font-display text-lg font-semibold tracking-tight ${
            tone === "danger" ? "text-destructive" : "text-foreground"
          }`}
        >
          {title}
        </h2>
        {description && (
          <p className="mt-1 max-w-prose text-sm leading-relaxed text-text-secondary">
            {description}
          </p>
        )}
        <div aria-hidden className="rule-printed mt-3 h-px w-full" />
      </div>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}
