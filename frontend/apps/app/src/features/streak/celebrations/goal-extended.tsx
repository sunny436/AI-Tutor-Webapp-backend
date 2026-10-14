import { PAINT } from "./palette";

/**
 * Animation 2, Daily Goal Completed + Streak Extended: the owner's asset (PadhAI Animation
 * Gallery, `svgGoal`), its markup, timing and CSS unchanged; only the colours come from the design
 * tokens. One combined animation, ~1.5 s: the check's circle pops, the check draws, the flame pops,
 * sparkles burst. The streak's number is the card's text, not part of the drawing. With reduced
 * motion the global rules (globals.css) show its last frame: circle, check and flame.
 */
const CSS = `
  .goal-circle-bg { transform-origin: 0px 0px; animation: goal-pop-in-circle 0.6s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
  .goal-check-path { stroke-dasharray: 60; stroke-dashoffset: 60; animation: goal-draw-check 0.5s 0.2s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
  .goal-flame-group { transform-origin: 0px 100px; transform: scale(0); animation: goal-pop-in-flame 0.8s 0.5s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
  .goal-sparkle-group { transform-origin: 0px 100px; }
  .goal-sparkle { opacity: 0; transform: scale(0); }
  .goal-sp-1 { animation: goal-burst 0.8s 0.6s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
  .goal-sp-2 { animation: goal-burst 0.8s 0.7s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
  .goal-sp-3 { animation: goal-burst 0.8s 0.65s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
  @keyframes goal-pop-in-circle {
    0% { transform: translate(-80px, -20px) scale(0); }
    60% { transform: translate(-80px, -20px) scale(1.1); }
    100% { transform: translate(-80px, -20px) scale(1); }
  }
  @keyframes goal-draw-check { to { stroke-dashoffset: 0; } }
  @keyframes goal-pop-in-flame {
    0% { transform: translate(40px, 0) scale(0); }
    60% { transform: translate(40px, 0) scale(1.05); }
    100% { transform: translate(40px, 0) scale(1); }
  }
  @keyframes goal-burst {
    0% { opacity: 0; transform: scale(0) translateY(0) rotate(-20deg); }
    20% { opacity: 1; }
    100% { opacity: 0; transform: scale(1) translateY(-40px) rotate(20deg); }
  }
`;

export function GoalExtended({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 512 512" className={className} aria-hidden data-celebration="extended">
      <style>{CSS}</style>
      <defs>
        <linearGradient id="goal-flame-base" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.flame }} />
          <stop offset="100%" style={{ stopColor: PAINT.flameTip }} />
        </linearGradient>
        <linearGradient id="goal-flame-inner" x1="0%" y1="100%" x2="0%" y2="0%">
          <stop offset="0%" style={{ stopColor: PAINT.gold }} />
          <stop offset="100%" style={{ stopColor: PAINT.goldTip }} />
        </linearGradient>
      </defs>
      <g transform="translate(256, 256)">
        <g className="goal-circle-bg">
          <circle cx="0" cy="0" r="50" style={{ fill: PAINT.soft }} />
          <path
            className="goal-check-path"
            d="M-15,0 L-5,10 L15,-10"
            fill="none"
            style={{ stroke: PAINT.brand }}
            strokeWidth="6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
        <g className="goal-sparkle-group">
          <g className="goal-sparkle goal-sp-1" transform="translate(130, -120)">
            <path
              d="M0,-12 C1.5,-4 4,-1.5 12,0 C4,1.5 1.5,4 0,12 C-1.5,4 -4,1.5 -12,0 C-4,-1.5 -1.5,-4 0,-12 Z"
              style={{ fill: PAINT.gold }}
            />
          </g>
          <g className="goal-sparkle goal-sp-2" transform="translate(170, -40)">
            <path
              d="M0,-8 C1,-3 3,-1 8,0 C3,1 1,3 0,8 C-1,3 -3,1 -8,0 C-3,-1 -1,-3 0,-8 Z"
              style={{ fill: PAINT.flame }}
            />
          </g>
          <g className="goal-sparkle goal-sp-3" transform="translate(-40, -90)">
            <path
              d="M0,-10 C1,-3 3,-1 10,0 C3,1 1,3 0,10 C-1,3 -3,1 -10,0 C-3,-1 -1,-3 0,-10 Z"
              style={{ fill: PAINT.gold }}
            />
          </g>
        </g>
        <g className="goal-flame-group">
          <path
            d="M0, -120 C60,-40 100,20 100,80 C100,140 50,180 0,180 C-50,180 -100,140 -100,80 C-100,20 -60,-40 0,-120 Z"
            fill="url(#goal-flame-base)"
          />
          <path
            d="M0, -40 C40,10 60,50 60,90 C60,125 35,150 0,150 C-35,150 -60,125 -60,90 C-60,50 -40,10 0,-40 Z"
            fill="url(#goal-flame-inner)"
          />
        </g>
      </g>
    </svg>
  );
}
