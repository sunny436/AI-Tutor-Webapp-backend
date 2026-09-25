/**
 * SAMPLE DATA for the preview UI — every placeholder in the app lives here.
 *
 * Nothing in this file is about the signed-in user or comes from the API. It is
 * shown only with preview features on (lib/preview.ts), always next to a
 * "Preview" label, and each export is replaced by real data when its backend
 * exists. Search for an import of this file to find everything still waiting.
 */

/** The streak, XP and class/board line in the sidebar. */
export const STUDENT_STATS = {
  streakDays: 7,
  xp: 1420,
  grade: "Class 10",
  board: "CBSE",
} as const;
