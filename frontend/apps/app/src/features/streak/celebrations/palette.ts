/**
 * The owner's flame palette (PadhAI Animation Gallery) as design tokens
 * (packages/ui/src/globals.css, where each one's colour is written down), for the celebrations'
 * SVG paint. The same colours in light mode; in dark mode the soft accent and the muted flame
 * turn dark so they stay soft on dark surfaces.
 */
export const PAINT = {
  flame: "hsl(var(--flame))",
  flameTip: "hsl(var(--flame-tip))",
  gold: "hsl(var(--flame-gold))",
  goldTip: "hsl(var(--flame-gold-tip))",
  soft: "hsl(var(--accent-soft))",
  muted: "hsl(var(--flame-muted))",
  brand: "hsl(var(--brand))",
  background: "hsl(var(--background))",
} as const;
