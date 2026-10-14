import { PAINT } from "./palette";

/**
 * Animation 4, Streak Lost: the owner's asset (PadhAI Animation Gallery, `svgLost`), its markup,
 * timing and CSS unchanged; only the colours come from the design tokens. Gentle, 1.5 s: the warm
 * flame fades into the muted one, which settles a little smaller, while the glow fades. With
 * reduced motion the global rules (globals.css) show its last frame: the muted, resting flame.
 */
const CSS = `
  .lost-flame-container { transform-origin: 0px 100px; animation: lost-flame-recede 1.5s cubic-bezier(0.4, 0, 0.2, 1) forwards; }
  .lost-active-flame { animation: lost-fade-out 1.5s cubic-bezier(0.4, 0, 0.2, 1) forwards; }
  .lost-glow { transform-origin: 0px 100px; opacity: 0.4; animation: lost-fade-out-glow 1.5s cubic-bezier(0.4, 0, 0.2, 1) forwards; }
  @keyframes lost-flame-recede { 0% { transform: scale(1); } 100% { transform: scale(0.85); } }
  @keyframes lost-fade-out { 0% { opacity: 1; } 100% { opacity: 0; } }
  @keyframes lost-fade-out-glow { 0% { opacity: 0.5; transform: scale(1.1); } 100% { opacity: 0; transform: scale(0.8); } }
`;

export function StreakLost({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 512 512" className={className} aria-hidden data-celebration="lost">
      <style>{CSS}</style>
      <defs>
        <filter id="lost-soft-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="24" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <linearGradient id="lost-flame-base" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.flame }} />
          <stop offset="100%" style={{ stopColor: PAINT.flameTip }} />
        </linearGradient>
        <linearGradient id="lost-flame-inner" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.gold }} />
          <stop offset="100%" style={{ stopColor: PAINT.goldTip }} />
        </linearGradient>
        <linearGradient id="lost-flame-muted" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.muted }} />
          <stop offset="100%" style={{ stopColor: PAINT.soft }} />
        </linearGradient>
        <linearGradient id="lost-inner-muted" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.soft }} />
          <stop offset="100%" style={{ stopColor: PAINT.background }} />
        </linearGradient>
      </defs>
      <g transform="translate(256, 256)">
        <g className="lost-flame-container">
          <circle
            className="lost-glow"
            cx="0"
            cy="40"
            r="120"
            style={{ fill: PAINT.flame }}
            filter="url(#lost-soft-glow)"
          />
          <g className="lost-muted-flame">
            <path
              d="M0, -120 C60,-40 100,20 100,80 C100,140 50,180 0,180 C-50,180 -100,140 -100,80 C-100,20 -60,-40 0,-120 Z"
              fill="url(#lost-flame-muted)"
            />
            <path
              d="M0, -40 C40,10 60,50 60,90 C60,125 35,150 0,150 C-35,150 -60,125 -60,90 C-60,50 -40,10 0,-40 Z"
              fill="url(#lost-inner-muted)"
            />
          </g>
          <g className="lost-active-flame">
            <path
              d="M0, -120 C60,-40 100,20 100,80 C100,140 50,180 0,180 C-50,180 -100,140 -100,80 C-100,20 -60,-40 0,-120 Z"
              fill="url(#lost-flame-base)"
            />
            <path
              d="M0, -40 C40,10 60,50 60,90 C60,125 35,150 0,150 C-35,150 -60,125 -60,90 C-60,50 -40,10 0,-40 Z"
              fill="url(#lost-flame-inner)"
            />
          </g>
        </g>
      </g>
    </svg>
  );
}
