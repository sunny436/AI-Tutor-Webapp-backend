/**
 * A reply as something to say: voice mode's spoken copy of the tutor's answer, made sentence by sentence while the
 * answer is still being written. What the chat shows is never changed.
 *
 * PARSED, NOT STRIPPED. Each part is parsed with the chat's own Markdown pipeline (remark-gfm, remark-math,
 * remark-tutor: message-content.tsx) and its tree is read in order: paragraphs, headings, list items (with their
 * numbers) and study cards (title, then text) are spoken; a link is its text; maths is read by latex.ts. What
 * cannot be read aloud faithfully is named instead, once per reply: code, a table, a diagram, the question
 * bank's questions, an attached file, a picture, and anything in Hindi (OllaLink speaks English only).
 *
 * WHILE IT STREAMS. The reply is cut into its blocks (blocks.ts splitBlocks: contiguous, so progress is a
 * character offset). A finished block is spoken whole; the block still arriving only up to its last complete
 * sentence (or finished list or heading line) before anything still open: a code fence, display maths or a
 * table, and only where its inline marks ($, `, **, [ ]) are balanced. (blocks.ts streamSafe is for showing:
 * it may close an open mark, so its text is not a prefix to cut at.)
 *
 * CHUNKS. Sentences are merged to at least MIN_CHUNK characters and split at a comma or a space past MAX_CHUNK,
 * so a request is neither a fragment nor a paragraph; the very first chunk ends at its first pause (a comma,
 * semicolon, colon or dash after FIRST_COMMA characters), even in a sentence that has already arrived whole, so
 * the voice starts sooner. Each chunk has the next sequence number.
 */

import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkParse from "remark-parse";
import { unified } from "unified";

import { splitBlocks } from "@/features/markdown/blocks";
import { remarkTutor } from "@/features/markdown/remark-tutor";
import { speakLatex } from "./latex";

export const MIN_CHUNK = 25;
export const MAX_CHUNK = 220;
export const FIRST_COMMA = 24; // was 40: the voice starts about three words sooner

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm, { singleTilde: false })
  .use(remarkMath)
  // biome-ignore lint/suspicious/noExplicitAny: the chat's own plugin, typed for react-markdown's processor
  .use(remarkTutor as any);

type MdNode = {
  type: string;
  value?: string;
  lang?: string | null;
  children?: MdNode[];
  ordered?: boolean | null;
  start?: number | null;
  data?: { directiveLabel?: boolean };
};

export type SpokenNote = "code" | "table" | "diagram" | "questions" | "file" | "picture" | "hindi";
export const NOTES: Record<SpokenNote, string> = {
  code: "There's some code in the chat.",
  table: "There's a table in the chat.",
  diagram: "There's a diagram in the chat.",
  questions: "I've put the questions in the chat.",
  file: "There's a file in the chat.",
  picture: "There's a picture in the chat.",
  hindi: "Part of this answer is in Hindi; you can read it in the chat.",
};
const QUESTION_LANGS = new Set(["question-bank", "mcq", "quiz", "flashcards", "fill-blank", "practice"]);
const DIAGRAM_LANGS = new Set(["mermaid", "chart", "graph", "diagram"]);
const DEVANAGARI = /[ऀ-ॿ]/;
const EMOJI = /\p{Extended_Pictographic}️?/gu;
// Outside maths: symbols a voice reads badly or not at all. Numbers and letters are never touched.
const SYMBOLS: [RegExp, string][] = [
  [/²/g, " squared"],
  [/³/g, " cubed"],
  [/×/g, " times "],
  [/÷/g, " divided by "],
  [/±/g, " plus or minus "],
  [/≤/g, " is less than or equal to "],
  [/≥/g, " is greater than or equal to "],
  [/≠/g, " is not equal to "],
  [/≈/g, " is approximately "],
  [/⇌/g, " is in equilibrium with "],
  [/→/g, " gives "],
  [/√/g, " the square root of "],
  [/π/g, " pi "],
  [/°/g, " degrees "],
  [/∞/g, " infinity "],
];

function symbols(text: string): string {
  let spoken = text.replace(EMOJI, "");
  for (const [pattern, words] of SYMBOLS) spoken = spoken.replace(pattern, words);
  return spoken;
}

type Unit = { text: string } | { note: SpokenNote };

function inline(node: MdNode): string {
  switch (node.type) {
    case "text":
      return symbols(node.value ?? "");
    case "inlineCode":
      return node.value ?? "";
    case "inlineMath":
      return ` ${speakLatex(node.value ?? "")} `;
    case "break":
      return " ";
    case "citation":
    case "html":
    case "image":
    case "imageReference":
    case "footnoteReference":
      return "";
    default:
      return (node.children ?? []).map(inline).join("");
  }
}

function hasImage(node: MdNode): boolean {
  return node.type === "image" || node.type === "imageReference" || (node.children ?? []).some(hasImage);
}

function units(node: MdNode, out: Unit[]): void {
  switch (node.type) {
    case "paragraph":
    case "heading": {
      let text = inline(node).trim();
      // A heading or a card's title is said as a line of its own, with a pause after it.
      if (text && (node.type === "heading" || node.data?.directiveLabel) && !/[.!?:;]$/.test(text)) text += ".";
      if (text) out.push({ text });
      else if (hasImage(node)) out.push({ note: "picture" });
      return;
    }
    case "code": {
      const lang = (node.lang ?? "").toLowerCase();
      out.push({ note: QUESTION_LANGS.has(lang) ? "questions" : DIAGRAM_LANGS.has(lang) ? "diagram" : "code" });
      return;
    }
    case "math":
      out.push({ text: speakLatex(node.value ?? "") });
      return;
    case "table":
      out.push({ note: "table" });
      return;
    case "leafDirective": // ::file / ::pdf: an attached file shown in the chat (remark-tutor.ts)
      out.push({ note: "file" });
      return;
    case "thematicBreak":
    case "html":
    case "definition":
    case "footnoteDefinition":
      return;
    case "list": {
      let number = node.start ?? 1;
      for (const item of node.children ?? []) {
        const before = out.length;
        units(item, out);
        const first = out[before];
        if (node.ordered && first && "text" in first) first.text = `${number}. ${first.text}`;
        number += 1;
      }
      return;
    }
    default: // root, blockquote (a card too), listItem, containerDirective (a study card: its title first)
      for (const child of node.children ?? []) units(child, out);
  }
}

const ABBREVIATION = /(?:^|[\s(])(?:e\.g|i\.e|etc|vs|Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|Fig|No|approx|cf|Eq|Ch|Vol|Ltd|Inc)\.$/i;
const INITIAL = /(?:^|\s)[A-Z]\.$/;
const LIST_NUMBER = /^\s*\d{1,3}[.)]$/; // "1." of a numbered step is not a sentence
const SENTENCE_END = /[.!?।]+["'”’)\]]*/g;

/** A spoken unit's sentences; an abbreviation, an initial or a decimal point never ends one. */
export function sentences(text: string): string[] {
  const out: string[] = [];
  let start = 0;
  for (const match of text.matchAll(SENTENCE_END)) {
    const end = (match.index ?? 0) + match[0].length;
    if (end < text.length && !/\s/.test(text[end] ?? "")) continue; // 3.14, example.com, "e.g.x"
    const candidate = text.slice(start, end);
    if (ABBREVIATION.test(candidate.trimEnd()) || INITIAL.test(candidate) || LIST_NUMBER.test(candidate)) continue;
    if (candidate.trim()) out.push(candidate.trim());
    start = end;
  }
  const rest = text.slice(start).trim();
  if (rest) out.push(rest);
  return out;
}

const CLAUSE = /[,;:](?= )| [—–](?= )/g;

/**
 * A reply's first words, up to their first pause (a comma, semicolon, colon or dash at least FIRST_COMMA
 * characters in), and the rest: the first request is short, so the voice starts sooner. A tutor's first sentence
 * is often 100 to 200 characters (measured 2026-10-26), a whole second of speech to make before the first word.
 * Kept whole when what would follow the pause is too short to stand on its own.
 */
export function firstClause(text: string): string[] {
  for (const found of text.matchAll(CLAUSE)) {
    const at = (found.index ?? 0) + found[0].length;
    if (at < FIRST_COMMA) continue;
    if (text.length - at < MIN_CHUNK) break;
    return [text.slice(0, at).trim(), text.slice(at).trim()];
  }
  return [text];
}

/** A long sentence in pieces of at most MAX_CHUNK, at a comma or semicolon if there is one, else at a space. */
export function split(text: string): string[] {
  const pieces: string[] = [];
  let rest = text.trim();
  while (rest.length > MAX_CHUNK) {
    const head = rest.slice(0, MAX_CHUNK);
    let at = Math.max(head.lastIndexOf(", "), head.lastIndexOf("; "));
    if (at < MIN_CHUNK) at = head.lastIndexOf(" ");
    if (at < MIN_CHUNK) at = MAX_CHUNK - 1;
    pieces.push(rest.slice(0, at + 1).trim());
    rest = rest.slice(at + 1).trim();
  }
  if (rest) pieces.push(rest);
  return pieces;
}

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const STRUCTURAL_LINE = /^\s{0,3}(?:[-*+]|\d{1,9}[.)]|#{1,6})\s/;

/** Whether `text`'s inline marks are all closed: never cut half a formula, half a code span or half a link. */
function balanced(text: string): boolean {
  const unescaped = text.replace(/\\[$`*[\]]/g, "");
  const code = unescaped.match(/`/g)?.length ?? 0;
  const prose = unescaped.replace(/`[^`]*`/g, "");
  const dollars = prose.match(/\$/g)?.length ?? 0;
  const bold = prose.match(/\*\*/g)?.length ?? 0;
  const opens = prose.match(/\[/g)?.length ?? 0;
  const closes = prose.match(/\]/g)?.length ?? 0;
  return code % 2 === 0 && dollars % 2 === 0 && bold % 2 === 0 && opens === closes;
}

/** How much of the block still arriving may be spoken now, counting from `from`; `from` when nothing yet. */
export function streamingCut(block: string, from: number, first: boolean): number {
  // Never into something still open: a code fence, display maths, a table at the end.
  let limit = block.length;
  let position = 0;
  let fenceAt = -1;
  for (const line of block.split("\n")) {
    if (FENCE.test(line)) fenceAt = fenceAt === -1 ? position : -1;
    position += line.length + 1;
  }
  if (fenceAt !== -1) limit = Math.min(limit, fenceAt);
  const displays = [...block.matchAll(/\$\$/g)];
  if (displays.length % 2 === 1) limit = Math.min(limit, displays[displays.length - 1]?.index ?? limit);
  const table = /(?:^|\n)(\s*\|[^\n]*(?:\n|$))+$/.exec(block);
  if (table) limit = Math.min(limit, table.index);
  if (limit <= from) return from;

  const window = block.slice(0, limit);
  let cut = from;
  for (const match of window.matchAll(SENTENCE_END)) {
    const end = (match.index ?? 0) + match[0].length;
    if (end <= from || end >= window.length || !/\s/.test(window[end] ?? "")) continue; // more must follow
    const lineStart = window.lastIndexOf("\n", (match.index ?? 0) - 1) + 1;
    if (LIST_NUMBER.test(window.slice(lineStart, end))) continue; // "2." opening the next step
    const candidate = window.slice(from, end);
    if (ABBREVIATION.test(candidate.trimEnd()) || INITIAL.test(candidate) || !balanced(candidate)) continue;
    cut = end;
  }
  // A finished line of a list or a heading is complete too.
  let lineStart = 0;
  for (const line of window.split("\n")) {
    const lineEnd = lineStart + line.length + 1;
    if (lineEnd <= window.length && lineEnd > cut && STRUCTURAL_LINE.test(line)) {
      if (balanced(window.slice(from, lineEnd))) cut = lineEnd;
    }
    lineStart = lineEnd;
  }
  // The first words of a reply may go at a comma, so the voice starts sooner.
  if (first && cut === from) {
    const comma = window.lastIndexOf(", ");
    if (comma - from >= FIRST_COMMA && balanced(window.slice(from, comma + 1))) cut = comma + 2;
  }
  return cut;
}

export type SpeechChunk = { seq: number; text: string };

/**
 * The spoken copy of one reply, fed the reply as it grows (`next`) and once more when it has finished
 * (`finish`): each call returns the chunks that are ready to say, in order, never the same words twice.
 */
export class SpeechChunker {
  private seq = 0;
  private spoken = 0; // characters of the reply already turned into speech
  private pending = ""; // speech not yet sent: a short sentence waiting for the next
  private readonly said = new Set<SpokenNote>();

  next(content: string): SpeechChunk[] {
    return this.take(content, false);
  }

  /** The reply's first `chars` characters were spoken elsewhere (the server's first words, as chunk 0). */
  skip(chars: number): void {
    this.spoken = Math.max(this.spoken, chars);
    this.seq = Math.max(this.seq, 1);
  }

  finish(content: string): SpeechChunk[] {
    return this.take(content, true);
  }

  private take(content: string, finished: boolean): SpeechChunk[] {
    const texts: string[] = [];
    const blocks = splitBlocks(content);
    let start = 0;
    blocks.forEach((block, index) => {
      const end = start + block.length;
      if (end > this.spoken) {
        const from = Math.max(this.spoken, start) - start;
        if (finished || index < blocks.length - 1) {
          texts.push(...this.say(block.slice(from)));
          this.spoken = end;
        } else {
          const cut = streamingCut(block, from, this.seq === 0 && !this.pending && texts.length === 0);
          if (cut > from) {
            texts.push(...this.say(block.slice(from, cut)));
            this.spoken = start + cut;
          }
        }
      }
      start = end;
    });
    return this.pack(texts, finished);
  }

  /** One piece of Markdown as spoken units, each note at most once per reply. */
  private say(markdown: string): string[] {
    if (!markdown.trim()) return [];
    const found: Unit[] = [];
    units(processor.runSync(processor.parse(markdown)) as MdNode, found);
    const texts: string[] = [];
    const note = (kind: SpokenNote) => {
      if (!this.said.has(kind)) texts.push(NOTES[kind]);
      this.said.add(kind);
    };
    for (const unit of found) {
      if ("note" in unit) {
        note(unit.note);
      } else if (DEVANAGARI.test(unit.text)) {
        note("hindi");
      } else {
        // A citation taken out leaves "food ." behind: punctuation goes back to its word.
        const text = unit.text.replace(/\s+/g, " ").replace(/\s+([.,!?;:])/g, "$1").trim();
        if (text) texts.push(text);
      }
    }
    return texts;
  }

  private pack(texts: string[], finished: boolean): SpeechChunk[] {
    const out: SpeechChunk[] = [];
    let buffer = this.pending;
    for (const sentence of texts.flatMap(sentences)) {
      buffer = buffer ? `${buffer} ${sentence}` : sentence;
      if (buffer.length >= MIN_CHUNK) {
        // Only a first sentence on its own: short ones joined together stay one chunk.
        const parts = this.seq === 0 && buffer === sentence ? firstClause(buffer) : [buffer];
        for (const part of parts) for (const piece of split(part)) out.push({ seq: this.seq++, text: piece });
        buffer = "";
      }
    }
    if (finished && buffer.trim()) {
      for (const piece of split(buffer)) out.push({ seq: this.seq++, text: piece });
      buffer = "";
    }
    this.pending = buffer;
    return out;
  }
}

/** A whole, finished reply as spoken chunks' text. */
export function speak(markdown: string): string[] {
  return new SpeechChunker().finish(markdown).map((chunk) => chunk.text);
}
