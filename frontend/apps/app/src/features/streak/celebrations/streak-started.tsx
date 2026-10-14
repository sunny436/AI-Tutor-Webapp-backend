import { PAINT } from "./palette";

/**
 * Animation 1, Streak Started: the owner's asset (PadhAI Animation Gallery, `svgStarted`), its
 * markup, timing and CSS unchanged; only the colours come from the design tokens. Plays once on
 * mount (1.6 s, sparkles to 2 s). Decorative: the toast's text says what happened. With reduced
 * motion the global rules (globals.css) show its last frame: the still flame.
 */
const CSS = `
  .start-flame-group {
    transform-origin: center 70%;
    animation: start-pop-in 1.6s cubic-bezier(0.25, 1, 0.5, 1) forwards;
  }
  .start-glow {
    transform-origin: center 70%;
    opacity: 0;
    animation: start-pulse-glow 1.6s cubic-bezier(0.25, 1, 0.5, 1) forwards;
  }
  .start-sparkle { transform-origin: center center; opacity: 0; }
  .start-sparkle-1 { animation: start-twinkle 1.6s 0.2s ease-in-out forwards; }
  .start-sparkle-2 { animation: start-twinkle 1.6s 0.4s ease-in-out forwards; }
  .start-sparkle-3 { animation: start-twinkle 1.6s 0.3s ease-in-out forwards; }
  @keyframes start-pop-in {
    0% { transform: scale(0.75); }
    40% { transform: scale(1.05); }
    70% { transform: scale(0.98); }
    100% { transform: scale(1); }
  }
  @keyframes start-pulse-glow {
    0% { opacity: 0; transform: scale(0.8); }
    30% { opacity: 0.4; transform: scale(1.2); }
    100% { opacity: 0; transform: scale(1.3); }
  }
  @keyframes start-twinkle {
    0% { opacity: 0; transform: scale(0) rotate(-15deg); }
    40% { opacity: 1; transform: scale(1) rotate(0deg); }
    100% { opacity: 0; transform: scale(0) rotate(15deg); }
  }
`;

export function StreakStarted({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 512 512" className={className} aria-hidden data-celebration="started">
      <style>{CSS}</style>
      <defs>
        <filter id="start-soft-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="24" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <linearGradient id="start-flame-base" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.flame }} />
          <stop offset="100%" style={{ stopColor: PAINT.flameTip }} />
        </linearGradient>
        <linearGradient id="start-flame-inner" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.gold }} />
          <stop offset="100%" style={{ stopColor: PAINT.goldTip }} />
        </linearGradient>
      </defs>
      <g transform="translate(256, 256)">
        <circle
          className="start-glow"
          cx="0"
          cy="40"
          r="120"
          style={{ fill: PAINT.flame }}
          filter="url(#start-soft-glow)"
        />
        <g className="start-flame-group">
          <path
            d="M0, -120 C60,-40 100,20 100,80 C100,140 50,180 0,180 C-50,180 -100,140 -100,80 C-100,20 -60,-40 0,-120 Z"
            fill="url(#start-flame-base)"
          />
          <path
            d="M0, -40 C40,10 60,50 60,90 C60,125 35,150 0,150 C-35,150 -60,125 -60,90 C-60,50 -40,10 0,-40 Z"
            fill="url(#start-flame-inner)"
          />
        </g>
        <g className="start-sparkle start-sparkle-1" transform="translate(110, -60)">
          <path
            d="M0,-15 C2,-5 5,-2 15,0 C5,2 2,5 0,15 C-2,5 -5,2 -15,0 C-5,-2 -2,-5 0,-15 Z"
            style={{ fill: PAINT.gold }}
          />
        </g>
        <g className="start-sparkle start-sparkle-2" transform="translate(-90, -30)">
          <path
            d="M0,-10 C1,-3 3,-1 10,0 C3,1 1,3 0,10 C-1,3 -3,1 -10,0 C-3,-1 -1,-3 0,-10 Z"
            style={{ fill: PAINT.gold }}
          />
        </g>
        <g className="start-sparkle start-sparkle-3" transform="translate(130, 40)">
          <path
            d="M0,-12 C1.5,-4 4,-1.5 12,0 C4,1.5 1.5,4 0,12 C-1.5,4 -4,1.5 -12,0 C-4,-1.5 -1.5,-4 0,-12 Z"
            style={{ fill: PAINT.flame }}
          />
        </g>
      </g>
    </svg>
  );
}
