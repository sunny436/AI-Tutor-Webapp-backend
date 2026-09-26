/**
 * SAMPLE DATA for the preview UI — every placeholder in the app lives here.
 *
 * Nothing in this file is about the signed-in user or comes from the API. It is
 * shown only with preview features on (lib/preview.ts), always next to a
 * "Preview" label, and each export is replaced by real data when its backend
 * exists. Search for an import of this file to find everything still waiting.
 */

/** My Courses: the overview banner and three courses with their chapters. */
export const COURSE_OVERVIEW = {
  tag: "Aligned with NCERT & ICSE 2026-27",
  title: "Class 10 CBSE & ICSE Syllabus",
  lead: "Track chapter completion, practice high-yield exam questions, and revise smart.",
  completion: "58% Finished",
  nextTest: "Science Ch 6 Life Processes",
} as const;

export type SampleChapter = { id: string; title: string; completed: boolean; active?: boolean; questions: number };
export type SampleCourse = { id: string; title: string; board: string; grade: string; progress: number; chapters: SampleChapter[] };

export const SYLLABUS: readonly SampleCourse[] = [
  {
    id: "sci-10",
    title: "Class 10 Science (CBSE)",
    board: "CBSE",
    grade: "Class 10",
    progress: 68,
    chapters: [
      { id: "ch-1", title: "Chemical Reactions and Equations", completed: true, questions: 12 },
      { id: "ch-2", title: "Acids, Bases and Salts", completed: true, questions: 15 },
      { id: "ch-3", title: "Metals and Non-metals", completed: true, questions: 18 },
      { id: "ch-6", title: "Life Processes", completed: false, active: true, questions: 24 },
      { id: "ch-10", title: "Light - Reflection and Refraction", completed: false, questions: 20 },
      { id: "ch-12", title: "Electricity", completed: false, questions: 22 },
    ],
  },
  {
    id: "math-10",
    title: "Class 10 Mathematics (CBSE)",
    board: "CBSE",
    grade: "Class 10",
    progress: 45,
    chapters: [
      { id: "m-1", title: "Real Numbers", completed: true, questions: 10 },
      { id: "m-2", title: "Polynomials", completed: true, questions: 14 },
      { id: "m-3", title: "Pair of Linear Equations in Two Variables", completed: false, active: true, questions: 19 },
      { id: "m-4", title: "Quadratic Equations", completed: false, questions: 16 },
    ],
  },
  {
    id: "phy-10-icse",
    title: "Class 10 Physics (ICSE)",
    board: "ICSE",
    grade: "Class 10",
    progress: 30,
    chapters: [
      { id: "p-1", title: "Force, Work, Power and Energy", completed: true, questions: 20 },
      { id: "p-2", title: "Light & Spectrum", completed: false, active: true, questions: 25 },
      { id: "p-3", title: "Sound & Echoes", completed: false, questions: 14 },
    ],
  },
];

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

/** Course Creator: the form's starting values and choices. */
export const STUDY_PLAN_FORM = {
  goal: "CBSE Class 10 Board Exam 2027",
  boards: ["CBSE", "ICSE", "State Board"],
  hours: ["2 Hours / Day", "3 Hours / Day", "4+ Hours / Day"],
} as const;

/** Flashcards: five cards across subjects. */
export const FLASHCARDS = [
  { id: 1, topic: "Chemistry", question: "What is the formula of Rust?", answer: "Fe₂O₃·xH₂O (Hydrated Ferric Oxide)", level: "Medium" },
  { id: 2, topic: "Biology", question: "Where does light reaction of Photosynthesis take place?", answer: "Thylakoid Membrane of Chloroplasts", level: "Easy" },
  { id: 3, topic: "Physics", question: "What is Snell’s Law of Refraction?", answer: "sin(i) / sin(r) = Refractive Index (n)", level: "Hard" },
  { id: 4, topic: "Maths", question: "What is the discriminant of a Quadratic Equation?", answer: "D = b² - 4ac", level: "Easy" },
  { id: 5, topic: "History", question: "When was the Non-Cooperation Movement launched by Gandhiji?", answer: "August 1, 1920", level: "Medium" },
] as const;
