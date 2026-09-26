/**
 * What each learning choice is called in the app. Every map is keyed by the contract's own
 * enum (lib/api/contract.gen.ts), so a value the API adds is a compile error here until it has
 * a name, rather than a blank on screen.
 */

import type { LearningPreferenceField, LearningPreferenceValues, MainGoal } from "@/lib/api/types";

export const MAIN_GOAL_LABELS: Record<MainGoal, string> = {
  board_exams: "Doing well in board exams",
  competitive_exam: "Preparing for a competitive exam",
  better_marks: "Better marks at school",
  understand_concepts: "Understanding concepts deeply",
  homework_help: "Help with homework",
  other: "Something else",
};

type Options<K extends LearningPreferenceField> = Record<LearningPreferenceValues[K], string>;

export type PreferenceInfo<K extends LearningPreferenceField> = {
  label: string;
  description: string;
  options: Options<K>;
};

const NONE = "No preference";

export const PREFERENCES: { [K in LearningPreferenceField]: PreferenceInfo<K> } = {
  language: {
    label: "Reply language",
    description: "The language the tutor answers in, unless you ask it for another one.",
    options: { auto: NONE, english: "English", hindi: "Hindi", hinglish: "Hinglish" },
  },
  explanationLevel: {
    label: "Explanations",
    description: "How deep the tutor goes.",
    options: { auto: NONE, simple: "Simple", standard: "Like a textbook", detailed: "Detailed" },
  },
  pace: {
    label: "Pace",
    description: "How quickly the tutor moves through a topic.",
    options: { auto: NONE, slow: "Slow", steady: "Steady", fast: "Fast" },
  },
  difficulty: {
    label: "Difficulty",
    description: "How hard examples and practice problems are.",
    options: { auto: NONE, easy: "Easy", medium: "Medium", hard: "Hard" },
  },
  realWorldExamples: {
    label: "Real-world examples",
    description: "Connecting ideas to everyday life.",
    options: { auto: NONE, more: "More", fewer: "Fewer" },
  },
  visualExplanations: {
    label: "Visual explanations",
    description: "Tables, step lists and simple text diagrams.",
    options: { auto: NONE, more: "More", fewer: "Fewer" },
  },
  personality: {
    label: "Tone",
    description: "How the tutor talks to you.",
    options: { auto: NONE, friendly: "Friendly", encouraging: "Encouraging", professional: "Professional" },
  },
  responseLength: {
    label: "Answer length",
    description: "How long answers are, unless you ask for more or less.",
    options: { auto: NONE, short: "Short", medium: "Medium", long: "Long" },
  },
  answerMode: {
    label: "How it answers problems",
    description: "Straight answers, a hint first, or guiding questions that lead you there.",
    options: { auto: NONE, direct: "Answer directly", hints_first: "Hint first", socratic: "Guiding questions" },
  },
  stepByStep: {
    label: "Step-by-step",
    description: "Breaking explanations and solutions into numbered steps.",
    options: { auto: NONE, on: "Always", off: "Only when I ask" },
  },
  askBeforeAnswer: {
    label: "Check what I know first",
    description: "One short question about what you already know before a new topic.",
    options: { auto: NONE, on: "Yes", off: "No" },
  },
  practiceQuestions: {
    label: "Practice questions",
    description: "A question or two to try after an explanation.",
    options: { auto: NONE, on: "Yes", off: "Only when I ask" },
  },
  mistakeCorrection: {
    label: "Correcting mistakes",
    description: "How the tutor points out what went wrong.",
    options: { auto: NONE, gentle: "Gently", direct: "Directly" },
  },
  highlightKeyConcepts: {
    label: "Highlight key ideas",
    description: "Key terms in bold and a one-line summary at the end.",
    options: { auto: NONE, on: "Yes", off: "No" },
  },
};

/** The Learning Preferences section, then the AI Tutor section: every field exactly once. */
export const LEARNING_FIELDS = [
  "language",
  "explanationLevel",
  "pace",
  "difficulty",
  "realWorldExamples",
  "visualExplanations",
] as const satisfies readonly LearningPreferenceField[];

export const TUTOR_FIELDS = [
  "personality",
  "responseLength",
  "answerMode",
  "stepByStep",
  "askBeforeAnswer",
  "practiceQuestions",
  "mistakeCorrection",
  "highlightKeyConcepts",
] as const satisfies readonly LearningPreferenceField[];
