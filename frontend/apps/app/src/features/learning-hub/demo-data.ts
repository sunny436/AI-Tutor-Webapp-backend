/**
 * SAMPLE DATA for the preview UI — every placeholder in the app lives here.
 *
 * Nothing in this file is about the signed-in user or comes from the API. It is
 * shown only with preview features on (lib/preview.ts), always next to a
 * "Preview" label, and each export is replaced by real data when its backend
 * exists. Search for an import of this file to find everything still waiting.
 */

/** Homework Helper: one worked example. */
export const HOMEWORK_EXAMPLE = {
  source: "Class 10 CBSE Math NCERT Ch 4",
  question: "Find the roots of the equation 2x² - 5x + 3 = 0 by factorization method.",
  steps: [
    {
      title: "Step 1: Split the middle term (-5x)",
      note: "Product needed = 2 × 3 = 6. Sum needed = -5. Factors are -2 and -3.",
      work: ["2x² - 2x - 3x + 3 = 0"],
    },
    { title: "Step 2: Factor by grouping", note: null, work: ["2x(x - 1) - 3(x - 1) = 0", "(2x - 3)(x - 1) = 0"] },
  ],
  answer: "Roots are x = 3/2 and x = 1",
} as const;

/** Summarizer: one summary. */
export const SUMMARY_EXAMPLE = {
  title: "Key Summary: Metals & Non-Metals (Class 10)",
  readTime: "2 Min Read",
  points: [
    {
      term: "Physical Properties",
      text: "Metals are malleable, ductile, and good conductors of electricity. Non-metals are brittle and non-conductive (except Graphite).",
    },
    {
      term: "Amphoteric Oxides",
      text: "Metal oxides that react with both acids and bases to produce salt and water (e.g., Al₂O₃, ZnO).",
    },
    {
      term: "Reactivity Series",
      text: "Potassium (K) & Sodium (Na) are most reactive; Gold (Au) & Platinum (Pt) are least.",
    },
    { term: "Ionic Bonds", text: "Formed by complete transfer of electrons from metals to non-metals (High melting point)." },
  ],
} as const;
