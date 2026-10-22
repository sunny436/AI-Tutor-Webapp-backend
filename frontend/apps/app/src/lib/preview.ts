/**
 * PREVIEW FEATURES: interface built ahead of its backend.
 *
 * The learning tools (homework, summaries), the leaderboard and the class/board
 * line exist as UI only, with sample data. None of it may reach a real user
 * looking like a working feature, so all of it is behind this one switch, and the
 * switch is OFF unless the server's environment says exactly `PREVIEW_FEATURES=1`.
 *
 * Production never sets it (deploy/env/web.env.example). A local or staging
 * build sets it to review the screens; every preview surface then says so on
 * screen ("Preview", "Soon"), so even there nothing passes for the real thing.
 *
 * Read on the server per request (the `(app)` layout is dynamic), not baked into
 * the client bundle, so one build serves both a gated and a preview server — which
 * is how the E2E suite checks both.
 */
export function previewEnabled(value: string | undefined = process.env.PREVIEW_FEATURES): boolean {
  return value === "1";
}
