/**
 * Practice tests on the client: which card a server record belongs to, and what a typed message
 * means to the waiting test. Everything else (the questions, the order, the grading, the score)
 * is the server's (lib/api/types.ts `Assessment`); nothing here keeps or scores answers.
 */

import { sha256Hex } from "@/lib/api/files";

export const LETTERS = "ABCDEFGH";

/** A test block's source as the server hashed it: \n line ends, no spaces or breaks around it. */
export function testSource(source: string): string {
  return source.replace(/\r\n?/g, "\n").replace(/^[ \t\n]+|[ \t\n]+$/g, "");
}

/** The record's `locator` when this block is the reply's test. */
export function testLocator(source: string): Promise<string> {
  return sha256Hex(new Blob([testSource(source)]));
}

export type TestCommand = { kind: "answer"; value: number } | { kind: "skip" } | { kind: "show" };

const SHOW = /^(?:next|next question|continue|go on|repeat|repeat (?:the )?question|show (?:the )?question)$/;
const SKIP = /^(?:skip|skip it|skip this|skip (?:this |the )?question)$/;
const ANSWER = /^(?:(?:option|answer|ans|my answer is|i choose|i pick)\s*[:-]?\s*)?\(?([a-h])\)?$/;

/**
 * A typed message that acts on the waiting test: a letter (`B`, `option c`, `(d)`), `skip`, or
 * `next` / `continue` / `repeat` (show the waiting question). Anything else (`explain`, a
 * question) is a message for the tutor. The chat applies it to its latest unfinished test only.
 */
export function parseTestCommand(text: string): TestCommand | null {
  const said = text.trim().toLowerCase().replace(/\s+/g, " ").replace(/[.!]+$/, "");
  if (SHOW.test(said)) return { kind: "show" };
  if (SKIP.test(said)) return { kind: "skip" };
  const letter = ANSWER.exec(said)?.[1];
  return letter ? { kind: "answer", value: LETTERS.indexOf(letter.toUpperCase()) } : null;
}
