/**
 * A reply's Markdown as independent blocks, and the safe-to-show part of a block still arriving.
 *
 * WHY BLOCKS. Parsing a reply (Markdown, maths, highlighting) costs time in its length. While a
 * reply streams, re-parsing all of it on every update costs time in the square of its length, so
 * a long answer gets slower the longer it runs. Split at the blank lines between top-level blocks,
 * each finished block is parsed once and only the last one, still growing, is parsed again.
 *
 * WHY THE SAME HTML. The blocks render as siblings in one container (message-content.tsx), and a
 * split is made only where parsing the parts gives exactly what parsing the whole gives: never
 * inside a code fence or display maths, never before a line that could continue a list or an
 * indented block, and not at all when the text has something that reaches across blocks (link
 * reference and footnote definitions, raw HTML that may span blank lines).
 */

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const MATH = /^ {0,3}\$\$/;
/** A study card opens (`:::name`, remark-tutor.ts) and closes (a bare run of at least as many colons). */
const CONTAINER_OPEN = /^ {0,3}(:{3,})[^\s:]/;
const CONTAINER_CLOSE = /^ {0,3}(:{3,})[ \t]*$/;
const TABLE_ROW = /^ {0,3}\|/;
/** A line after a blank line that could belong to what came before (a list item, indented text). */
const CONTINUES = /^(?:\s|[-*+](?:\s|$)|\d{1,9}[.)](?:\s|$))/;
/** Enough of a line's start to know whether it CONTINUES, and so a decision that never changes. */
const DECIDED = /^(?:\s|[-*+].|\d{1,9}[.)].|\d{1,9}[^\d.)]|\d{10}|[^\s\d*+-])/;
/** Things that reach across blank lines: definitions used elsewhere, raw HTML blocks that span them. */
const WHOLE = /^ {0,3}\[[^\]\n]+\]:|<(?:pre|script|style|textarea)\b|<!--/im;

function displayMathOpens(line: string): boolean {
  return MATH.test(line) && !(line.trim().length >= 4 && line.trimEnd().endsWith("$$"));
}

/** Splits `text` into blocks; `blocks.join("") === text` always. */
export function splitBlocks(text: string): string[] {
  if (WHOLE.test(text)) return [text];
  const blocks: string[] = [];
  let start = 0;
  let fence: string | null = null;
  let math = false;
  let blank = false; // the previous line was blank (outside fences and maths)
  // Open study cards, as their colon counts: never split inside one (a card is one element).
  const cards: number[] = [];
  let position = 0;
  while (position < text.length) {
    const newline = text.indexOf("\n", position);
    const complete = newline !== -1;
    const line = text.slice(position, complete ? newline : text.length);

    // The first line after a blank one starts a new block, unless it may continue the last one.
    // A line too short to tell ("1" may become "1. item") waits until it can.
    if (
      blank &&
      cards.length === 0 &&
      position > start &&
      line.trim() !== "" &&
      (complete || DECIDED.test(line)) &&
      !CONTINUES.test(line)
    ) {
      blocks.push(text.slice(start, position));
      start = position;
    }

    const marker = FENCE.exec(line)?.[1];
    // Inside a card its closing line wins over anything open inside it, as the parser does: it
    // closes the outermost card with no more colons than it has, and everything inside that.
    const closer = cards.length ? CONTAINER_CLOSE.exec(line)?.[1]?.length : undefined;
    const closes = closer === undefined ? -1 : cards.findIndex((count) => count <= closer);
    if (closes !== -1) {
      cards.length = closes;
      fence = null;
      math = false;
      blank = false;
    } else if (fence !== null) {
      // A closing fence: the same character, at least as long, and nothing after it.
      if (marker && marker[0] === fence[0] && marker.length >= fence.length && line.trim() === marker) fence = null;
      blank = false;
    } else if (math) {
      if (MATH.test(line) || line.trimEnd().endsWith("$$")) math = false;
      blank = false;
    } else if (marker) {
      fence = marker;
      blank = false;
    } else if (displayMathOpens(line)) {
      math = true;
      blank = false;
    } else if (CONTAINER_OPEN.test(line)) {
      cards.push(CONTAINER_OPEN.exec(line)?.[1]?.length ?? 3);
      blank = false;
    } else {
      blank = complete && line.trim() === "";
    }
    position = complete ? newline + 1 : text.length;
  }
  blocks.push(text.slice(start));
  return blocks;
}

/**
 * The part of a block still arriving that is safe to show: never a half-typed construct that
 * would flash as raw symbols or a red maths error for a moment. Used only for the last block of
 * a live reply; a finished reply is always shown exactly as written.
 */
export function streamSafe(block: string): string {
  const lines = block.split("\n");
  // Inside an open code fence the text is code already: show it as it comes.
  if (lines.filter((line) => FENCE.test(line)).length % 2 === 1) return block;

  // Display maths not yet closed: wait for its closing $$.
  if ((block.match(/\$\$/g)?.length ?? 0) % 2 === 1) return block.slice(0, block.lastIndexOf("$$")).trimEnd();

  const lastComplete = block.lastIndexOf("\n");
  const typing = lines[lines.length - 1] ?? "";
  // A table appears once its header and divider rows are complete, then a whole row at a time.
  if (block.trimStart().startsWith("|")) {
    const completeRows = lines.slice(0, -1).filter((line) => line.trim() !== "").length;
    if (completeRows < 2) return "";
    if (typing.trim() !== "") return block.slice(0, lastComplete);
  } else if (TABLE_ROW.test(typing)) {
    // A table after other text (inside a study card): the same rule for its own rows.
    let first = lines.length - 1;
    while (first > 0 && TABLE_ROW.test(lines[first - 1] ?? "")) first--;
    if (lines.length - 1 - first < 2) return lines.slice(0, first).join("\n").trimEnd();
    return block.slice(0, lastComplete);
  }

  // The line being typed.
  const done = block.slice(0, lastComplete + 1);
  // A heading or list marker with nothing after it yet.
  if (/^\s{0,3}(?:#{1,6}|[-*+]|\d{1,9}[.)])\s*$/.test(typing) && typing !== "") return done.trimEnd();
  // A card's opening or closing line, a `::file` line, or an alert marker (`> [!NOTE`) still
  // being typed: shown once the line is whole.
  if (/^ {0,3}:/.test(typing) || /^\s{0,3}>\s*\[!?[A-Za-z]*\]?\s*$/.test(typing)) return done.trimEnd();
  let tail = typing;
  // An unfinished link: its text shows once the whole link has arrived.
  const link = tail.search(/\[[^\]]*\]\([^)]*$/);
  if (link !== -1) tail = tail.slice(0, link);
  // Inline maths not yet closed: wait for its closing $. Money ("$5 and", a number then a space)
  // shows at once; "$6CO_2" is maths that happens to start with a digit.
  const dollars = [...tail.matchAll(/(?<!\\)\$/g)].map((match) => match.index ?? 0);
  const open = dollars[dollars.length - 1];
  if (dollars.length % 2 === 1 && open !== undefined && !/^(?:\s|\d[\d,.]*\s)/.test(tail.slice(open + 1))) {
    tail = tail.slice(0, open);
  }
  // Inline code and bold still open: close them for now (or drop a marker with nothing after it).
  if ((tail.match(/`/g)?.length ?? 0) % 2 === 1) tail = tail.endsWith("`") ? tail.slice(0, -1) : `${tail}\``;
  if ((tail.replace(/`[^`]*`/g, "").match(/\*\*/g)?.length ?? 0) % 2 === 1) {
    tail = tail.endsWith("**") ? tail.slice(0, -2) : `${tail.trimEnd()}**`;
  }
  return done + tail;
}
