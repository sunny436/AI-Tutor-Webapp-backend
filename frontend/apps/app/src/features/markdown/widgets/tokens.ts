/**
 * Design tokens as concrete colours, for the libraries that draw themselves (Chart.js on a
 * canvas, mermaid's theme): they cannot read `hsl(var(--x))`. Read at draw time, so the light,
 * dark and high-contrast themes all apply; callers draw again when the theme changes.
 */

function channel(value: number): string {
  return Math.round(Math.min(255, Math.max(0, value * 255)))
    .toString(16)
    .padStart(2, "0");
}

/** `--name` (an "H S% L%" triplet in globals.css) as #rrggbb, or #rrggbbaa with an alpha. */
export function token(name: string, alpha = 1): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  const [h = 0, s = 0, l = 0] = raw.split(/[\s,/]+/).map((part) => Number.parseFloat(part));
  const sat = s / 100;
  const light = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const f = (n: number) => light - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return `#${channel(f(0))}${channel(f(8))}${channel(f(4))}${alpha < 1 ? channel(alpha) : ""}`;
}

/** The chart series colours (--chart-1..6: the validated categorical order, light and dark). */
export function series(): string[] {
  return [1, 2, 3, 4, 5, 6].map((slot) => token(`chart-${slot}`));
}

export function prefersReducedMotion(): boolean {
  return (
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document.documentElement.getAttribute("data-motion") === "reduce"
  );
}

/** JSON the model wrote, or null. */
export function parseJson(source: string): unknown {
  try {
    return JSON.parse(source);
  } catch {
    return null;
  }
}
