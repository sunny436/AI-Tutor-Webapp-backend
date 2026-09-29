import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { splitBlocks, streamSafe } from "./blocks";
import { Markdown, MessageContent } from "./message-content";

const whole = (text: string) => renderToStaticMarkup(<Markdown text={text} />);
const inBlocks = (text: string) =>
  renderToStaticMarkup(<MessageContent content={text} />).replace(/^<div[^>]*>|<\/div>$/g, "");

/** Replies shaped like the tutor's: every construct, and the tricky joins between them. */
const REPLIES = [
  "# Photosynthesis\n\nPlants make **food** from light.\n\n## Steps\n\n1. Light is absorbed\n2. Water splits\n\nDone.",
  "Loose list:\n\n- one\n\n- two\n\n- three\n\nAfter.",
  "Ordered, loose:\n\n1. first\n\n2. second\n\n   indented continuation\n\n3. third",
  "Code:\n\n```python\ndef f():\n\n    return 1\n\n\nprint(f())\n```\n\nAfter the code.",
  "~~~\nfence with tildes\n\n~~~\n\nText.",
  "Maths:\n\n$$\n\\int_0^1 x\\,dx\n\n= \\frac{1}{2}\n$$\n\nInline $e^{i\\pi}+1=0$ too.",
  "| a | b |\n|---|---|\n| 1 | 2 |\n\n| c |\n|---|\n| 3 |",
  "> quote one\n\n> quote two\n\nPlain.",
  "Indented code:\n\n    line one\n\n    line two\n\nEnd.",
  "Text with [a link](https://example.com) and a footnote.[^1]\n\n[^1]: The note.",
  "See [the docs][ref].\n\n[ref]: https://example.com/docs",
  "<pre>\nraw\n\nhtml\n</pre>\n\nAfter.",
  "Para one\n\n\n\nPara two after several blank lines.\n\n",
  "- a\n- b\n\n-5 degrees is cold.\n\n12.5 percent.\n\n* * *\n\n**Bold start** line.",
  "Setext\n======\n\nNext\n----\n\nBody.",
  "",
  "single block with no blank lines\nsecond line",
];

describe("splitBlocks", () => {
  test("the blocks always join back to the text", () => {
    for (const reply of REPLIES) expect(splitBlocks(reply).join("")).toBe(reply);
  });

  test("splits at blank lines between top-level blocks", () => {
    expect(splitBlocks("# T\n\nPara.\n\n## U\n\nMore.")).toEqual(["# T\n\n", "Para.\n\n", "## U\n\n", "More."]);
  });

  test("never inside a code fence or display maths, never before a list item or indented line", () => {
    expect(splitBlocks("```\na\n\nb\n```\n\nc")).toEqual(["```\na\n\nb\n```\n\n", "c"]);
    expect(splitBlocks("$$\na\n\nb\n$$\n\nc")).toEqual(["$$\na\n\nb\n$$\n\n", "c"]);
    expect(splitBlocks("- a\n\n- b\n\nc")).toEqual(["- a\n\n- b\n\n", "c"]);
    expect(splitBlocks("1. a\n\n   more\n\nc")).toEqual(["1. a\n\n   more\n\n", "c"]);
  });

  test("not at all when something reaches across blocks", () => {
    expect(splitBlocks("a [x][r]\n\n[r]: https://e.com")).toHaveLength(1);
    expect(splitBlocks("a[^1]\n\n[^1]: note")).toHaveLength(1);
    expect(splitBlocks("<pre>\na\n\nb\n</pre>")).toHaveLength(1);
    expect(splitBlocks("a\n\n<!-- c\n\nd -->")).toHaveLength(1);
  });

  test("a split, once made, never moves as the text grows", () => {
    // (A definition or raw HTML arriving later makes the reply one block: rare, and the same HTML.)
    const text = REPLIES.filter((reply) => !/\]:|<pre>/.test(reply)).join("\n\n");
    let previous: string[] = [];
    for (let length = 0; length <= text.length; length++) {
      const blocks = splitBlocks(text.slice(0, length));
      // Every finished block of the shorter text is still a block, unchanged, in the longer one.
      for (const [index, block] of previous.slice(0, -1).entries()) expect(blocks[index]).toBe(block);
      previous = blocks;
    }
  });

  // Every reply rendered twice, with KaTeX: a busy machine can pass bun's 5 s default.
  test("blocks render exactly the HTML of the whole reply", () => {
    for (const reply of REPLIES) expect(inBlocks(reply)).toBe(whole(reply));
  }, 60_000);
});

describe("streamSafe", () => {
  const cases: [string, string][] = [
    ["Plain words so far", "Plain words so far"],
    ["Some **bold", "Some **bold**"],
    ["Some **", "Some "],
    ["Use `code", "Use `code`"],
    ["Use `", "Use "],
    ["Energy is $E = mc", "Energy is "],
    ["It costs $5 and", "It costs $5 and"],
    ["It costs $5", "It costs "],
    ["Energy: $6CO_2 + 6", "Energy: "],
    ["Closed $x^2$ maths", "Closed $x^2$ maths"],
    ["See [the docs](https://exa", "See "],
    ["See [the docs](https://example.com) now", "See [the docs](https://example.com) now"],
    ["Intro\n\n$$\n\\frac{a}{", "Intro"],
    ["$$x$$ done", "$$x$$ done"],
    ["Line one\n#", "Line one"],
    ["Line one\n## ", "Line one"],
    ["List\n- ", "List"],
    ["| a | b |", ""],
    ["| a | b |\n|---", ""],
    ["| a | b |\n|---|---|\n| 1 |", "| a | b |\n|---|---|"],
    ["| a | b |\n|---|---|\n| 1 | 2 |\n", "| a | b |\n|---|---|\n| 1 | 2 |\n"],
    ["```py\nprint('**'", "```py\nprint('**'"],
  ];
  for (const [input, expected] of cases) {
    test(JSON.stringify(input), () => expect(streamSafe(input)).toBe(expected));
  }

  test("no prefix of a reply ever renders a maths error, raw maths or a stray bold marker", () => {
    const reply =
      "## Energy\n\nEinstein: $E = mc^2$ and **mass** matters; $6CO_2 + 6H_2O$ too.\n\n$$\n\\frac{a}{b}\n$$\n\nDone `x`.";
    for (let length = 1; length <= reply.length; length++) {
      const html = renderToStaticMarkup(<MessageContent content={reply.slice(0, length)} streaming />);
      expect(html).not.toContain("katex-error");
      // Visible text only (KaTeX keeps the source in a hidden <annotation>).
      const text = html.replace(/<annotation[\s\S]*?<\/annotation>/g, "").replace(/<[^>]+>/g, "");
      expect(text).not.toContain("**");
      expect(text).not.toMatch(/\$|\\frac|CO_2/);
    }
    // About 120 full renders with KaTeX: correctness, not speed. A busy machine (CI, a Linux
    // container) takes longer than bun's 5 s default, so it gets its own limit.
  }, 60_000);
});
