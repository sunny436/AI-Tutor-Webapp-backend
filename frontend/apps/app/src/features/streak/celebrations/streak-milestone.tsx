import { PAINT } from "./palette";

/**
 * Animation 3, Weekly Streak Milestone: the owner's asset (PadhAI Animation Gallery,
 * `svgMilestone`), its markup, timing and CSS unchanged; only the colours come from the design
 * tokens. One drawing for every milestone (7, 14, 21, …): the number is the dialog's text. A 3 s
 * timeline played once (the flame bounces, a gold ring expands, 8 particles burst; motion ends
 * near 1.3 s). With reduced motion the global rules (globals.css) show its last frame: the flame.
 */
const CSS = `
  .ms-flame-group { transform-origin: 0px 100px; animation: ms-flame-bounce 3s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
  .ms-ring { transform-origin: 0px 60px; opacity: 0; animation: ms-ring-expand 3s ease-out forwards; }
  .ms-particle-group { transform-origin: 0px 60px; }
  .ms-particle { animation: ms-particle-shoot 3s cubic-bezier(0.25, 1, 0.5, 1) forwards; opacity: 0; }
  .ms-pg-1 { transform: rotate(0deg); } .ms-pg-2 { transform: rotate(45deg); }
  .ms-pg-3 { transform: rotate(90deg); } .ms-pg-4 { transform: rotate(135deg); }
  .ms-pg-5 { transform: rotate(180deg); } .ms-pg-6 { transform: rotate(225deg); }
  .ms-pg-7 { transform: rotate(270deg); } .ms-pg-8 { transform: rotate(315deg); }
  @keyframes ms-flame-bounce {
    0% { transform: scale(0); } 12% { transform: scale(1.15); }
    22% { transform: scale(0.95); } 32% { transform: scale(1.02); }
    42%, 100% { transform: scale(1); }
  }
  @keyframes ms-ring-expand {
    0% { transform: scale(0.2); opacity: 0; stroke-width: 24px; }
    5% { opacity: 0.6; }
    25%, 100% { transform: scale(1.6); opacity: 0; stroke-width: 2px; }
  }
  @keyframes ms-particle-shoot {
    0% { transform: translateY(-40px) scale(0.5); opacity: 0; }
    8% { opacity: 1; }
    28%, 100% { transform: translateY(-180px) scale(1); opacity: 0; }
  }
`;

export function StreakMilestone({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 512 512" className={className} aria-hidden data-celebration="milestone">
      <style>{CSS}</style>
      <defs>
        <linearGradient id="ms-flame-base" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.flame }} />
          <stop offset="100%" style={{ stopColor: PAINT.flameTip }} />
        </linearGradient>
        <linearGradient id="ms-flame-inner" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.gold }} />
          <stop offset="100%" style={{ stopColor: PAINT.goldTip }} />
        </linearGradient>
      </defs>
      <g transform="translate(256, 256)">
        <circle className="ms-ring" cx="0" cy="0" r="100" fill="none" style={{ stroke: PAINT.gold }} />
        <g className="ms-particle-group ms-pg-1">
          <circle className="ms-particle" cx="0" cy="0" r="8" style={{ fill: PAINT.flame }} />
        </g>
        <g className="ms-particle-group ms-pg-2">
          <rect className="ms-particle" x="-4" y="-7" width="8" height="14" rx="4" style={{ fill: PAINT.gold }} />
        </g>
        <g className="ms-particle-group ms-pg-3">
          <circle className="ms-particle" cx="0" cy="0" r="10" style={{ fill: PAINT.soft }} />
        </g>
        <g className="ms-particle-group ms-pg-4">
          <rect className="ms-particle" x="-3" y="-6" width="6" height="12" rx="3" style={{ fill: PAINT.flame }} />
        </g>
        <g className="ms-particle-group ms-pg-5">
          <circle className="ms-particle" cx="0" cy="0" r="7" style={{ fill: PAINT.brand }} />
        </g>
        <g className="ms-particle-group ms-pg-6">
          <rect className="ms-particle" x="-4" y="-8" width="8" height="16" rx="4" style={{ fill: PAINT.gold }} />
        </g>
        <g className="ms-particle-group ms-pg-7">
          <circle className="ms-particle" cx="0" cy="0" r="9" style={{ fill: PAINT.soft }} />
        </g>
        <g className="ms-particle-group ms-pg-8">
          <rect className="ms-particle" x="-3" y="-6" width="6" height="12" rx="3" style={{ fill: PAINT.flame }} />
        </g>
        <g className="ms-flame-group">
          <path
            d="M0, -120 C60,-40 100,20 100,80 C100,140 50,180 0,180 C-50,180 -100,140 -100,80 C-100,20 -60,-40 0,-120 Z"
            fill="url(#ms-flame-base)"
          />
          <path
            d="M0, -40 C40,10 60,50 60,90 C60,125 35,150 0,150 C-35,150 -60,125 -60,90 C-60,50 -40,10 0,-40 Z"
            fill="url(#ms-flame-inner)"
          />
        </g>
      </g>
    </svg>
  );
}
