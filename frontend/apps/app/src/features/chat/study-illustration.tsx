/**
 * The quiet picture above a new chat's greeting: an open book, a sprout of two leaves, three
 * small sparkles. Drawn in the design tokens at low strength (paper, hairlines, the brand's
 * blue and sage), so it follows the theme and never outweighs the greeting or the composer.
 * Decorative (`aria-hidden`), and gone on short screens, where the composer needs the room.
 */
export function StudyIllustration() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 120 90"
      data-study-illustration=""
      className="mx-auto mb-3 h-16 w-auto sm:mb-4 sm:h-[5.5rem] [@media(max-height:599px)]:hidden"
    >
      <ellipse cx="60" cy="81" rx="40" ry="3.5" className="fill-brand/10" />
      <path d="M58 40C46 34 31 33 16 36v38c15-3 30-2 42 4z" className="fill-card stroke-border" strokeWidth="1.5" />
      <path d="M62 40c12-6 27-7 42-4v38c-15-3-30-2-42 4z" className="fill-card stroke-border" strokeWidth="1.5" />
      <path d="M60 41v37" className="stroke-border" strokeWidth="1.5" />
      <g className="stroke-brand/25" strokeWidth="1.5" strokeLinecap="round" fill="none">
        <path d="M24 46c9-2 19-1 28 3" />
        <path d="M24 54c9-2 19-1 28 3" />
        <path d="M24 62c9-2 19-1 28 3" />
        <path d="M68 49c9-4 19-5 28-3" />
        <path d="M68 57c9-4 19-5 28-3" />
        <path d="M68 65c9-4 19-5 28-3" />
      </g>
      <path d="M60 40c0-8-1-14 1-22" className="stroke-sage" strokeWidth="2" strokeLinecap="round" fill="none" />
      <path d="M61 22c5-10 15-12 21-11-2 8-11 14-21 12z" className="fill-sage/50" />
      <path d="M60 29c-5-6-13-7-18-5 3 6 11 9 18 7z" className="fill-brand/30" />
      <path d="M26 14l1 3 3 1-3 1-1 3-1-3-3-1 3-1z" className="fill-streak/40" />
      <path d="M97 18l1 3 3 1-3 1-1 3-1-3-3-1 3-1z" className="fill-brand/30" />
      <path d="M102 52l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" className="fill-sage/40" />
    </svg>
  );
}
