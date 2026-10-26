import { describe, expect, test } from "bun:test";

import { speakLatex } from "./latex";
import { MAX_CHUNK, NOTES, SpeechChunker, sentences, speak, split } from "./speech-text";

describe("maths read aloud (latex.ts): structure kept, every number exact, nothing dropped", () => {
  const cases: [string, string][] = [
    ["x^2", "x squared"],
    ["x^3", "x cubed"],
    ["x^{n+1}", "x to the power n plus 1"],
    ["x^{-1}", "x to the power minus 1"],
    ["\\frac{a}{b}", "a over b"],
    ["\\frac{1}{2}", "1 over 2"],
    ["\\frac{a+b}{2}", "the fraction a plus b, over 2"],
    ["\\sqrt{x}", "the square root of x"],
    ["\\sqrt[3]{27}", "the cube root of 27"],
    ["-5 + 3 = -2", "minus 5 plus 3 equals minus 2"],
    ["6.022 \\times 10^{23}", "6.022 times 10 to the power 23"],
    ["9.8\\,\\text{m/s}^2", "9.8 m/s squared"],
    ["0.5", "0.5"],
    ["(a+b)^2", "the quantity a plus b, squared"],
    ["2(x+3)", "2 times the quantity x plus 3"],
    ["f(x) = x^2", "f of x equals x squared"],
    ["\\alpha + \\beta", "alpha plus beta"],
    ["\\pi r^2", "pi r squared"],
    ["30^\\circ", "30 degrees"],
    ["a \\leq b", "a is less than or equal to b"],
    ["x \\neq 0", "x is not equal to 0"],
    ["\\ce{H2O}", "H 2 O"],
    ["\\mathrm{CO_2}", "CO 2"],
    ["2H_2 + O_2 \\rightarrow 2H_2O", "2 H 2 plus O 2 gives 2 H 2 O"],
    ["\\Delta x", "delta x"],
    ["\\left( x \\right)", "the quantity x"],
    ["\\unknownthing{y}", "unknownthing y"], // said by its name, never dropped
    ["a}b", "a b"], // a stray brace does not end the formula
  ];
  for (const [latex, spoken] of cases) {
    test(`${latex} → ${spoken}`, () => {
      expect(speakLatex(latex)).toBe(spoken);
    });
  }
});

describe("a reply's spoken copy (speech-text.ts)", () => {
  test("Markdown is read, not spoken: emphasis, links and citations go, the words stay", () => {
    expect(speak("**Photosynthesis** is how plants make *their own* food [1].")).toEqual([
      "Photosynthesis is how plants make their own food.",
    ]);
    expect(speak("Read the [NCERT book](https://ncert.nic.in/textbook.php) for chapter one.")).toEqual([
      "Read the NCERT book for chapter one.",
    ]);
  });

  test("numbers, decimals, signs and units are said exactly as written", () => {
    const spoken = speak("The answer is −3.5 m/s². Mix 2.5 kg of sand with 10,000 L of water at 25°C.").join(" ");
    expect(spoken).toContain("−3.5 m/s squared");
    expect(spoken).toContain("2.5 kg");
    expect(spoken).toContain("10,000 L");
    expect(spoken).toContain("25 degrees C");
  });

  test("inline and display maths are read by the formula reader", () => {
    expect(speak("The area is $\\pi r^2$, so it grows fast.")).toEqual(["The area is pi r squared, so it grows fast."]);
    expect(speak("Newton's second law:\n\n$$F = ma$$")).toEqual(["Newton's second law: F equals ma"]);
  });

  test("headings, numbered steps and study cards are said in order, with a pause after a title", () => {
    expect(speak("## Steps\n\n1. Mix the flour.\n2. Add water.\n3. Knead it well.")).toEqual([
      "Steps. 1. Mix the flour. 2. Add water.",
      "3. Knead it well.",
    ]);
    expect(speak(":::note[Remember]\nWater boils at 100 degrees at sea level.\n:::")).toEqual([
      "Remember. Water boils at 100 degrees at sea level.",
    ]);
    expect(speak("> [!TIP]\n> Read the question twice before you answer it.")).toEqual([
      "Read the question twice before you answer it.",
    ]);
  });

  test("what can't be read aloud faithfully is named, once per reply", () => {
    const reply = [
      "Here is how it works in code.",
      "```python\nprint(1.5 * 2)\n```",
      "| a | b |\n| - | - |\n| 1 | 2 |",
      "Another table follows here too.",
      "| c | d |\n| - | - |\n| 3 | 4 |",
      "```mermaid\ngraph TD; A-->B\n```",
      "```question-bank\n{\"chapter\": 1}\n```",
      "::file{ref=F1}",
      "![a cell](https://example.com/cell.png)",
    ].join("\n\n");
    const spoken = speak(reply).join(" ");
    for (const note of [NOTES.code, NOTES.table, NOTES.diagram, NOTES.questions, NOTES.file, NOTES.picture]) {
      expect(spoken.split(note).length - 1).toBe(1);
    }
    expect(spoken).not.toContain("print");
    expect(spoken).not.toContain("|");
  });

  test("Hindi is not spoken (OllaLink speaks English only): it is named instead", () => {
    expect(speak("That is a good question.\n\nयह हिंदी में है।")).toEqual([`That is a good question. ${NOTES.hindi}`]);
  });

  test("sentences: never at an abbreviation, an initial, a decimal or a web address", () => {
    expect(sentences("Use a solvent, e.g. water. Then stir it.")).toEqual(["Use a solvent, e.g. water.", "Then stir it."]);
    expect(sentences("A. P. J. Abdul Kalam was a scientist. He was President.")).toEqual([
      "A. P. J. Abdul Kalam was a scientist.",
      "He was President.",
    ]);
    expect(sentences("g is 9.8 m/s. Visit ncert.nic.in for books. Done!")).toEqual([
      "g is 9.8 m/s.",
      "Visit ncert.nic.in for books.",
      "Done!",
    ]);
  });

  test("chunks are never fragments nor paragraphs: short sentences join, long ones split at a comma", () => {
    expect(speak("Yes. That's right. Well done today.")).toEqual(["Yes. That's right. Well done today."]);
    // A long first sentence goes at its first pause, so the voice starts sooner; a short tail stays on.
    expect(speak("Osmosis is the movement of water molecules, from a dilute solution to a concentrated one.")).toEqual([
      "Osmosis is the movement of water molecules,",
      "from a dilute solution to a concentrated one.",
    ]);
    expect(speak("The area is pi r squared, so it grows fast.")).toEqual(["The area is pi r squared, so it grows fast."]);
    const long = `${"Plants take in carbon dioxide from the air, ".repeat(8)}and give out oxygen.`;
    const pieces = speak(long);
    expect(pieces.length).toBeGreaterThan(1);
    for (const piece of pieces) expect(piece.length).toBeLessThanOrEqual(MAX_CHUNK);
    expect(pieces.join(" ").replace(/\s+/g, " ")).toBe(long.replace(/\s+/g, " ").trim());
    expect(split("x".repeat(500)).every((piece) => piece.length <= MAX_CHUNK)).toBe(true);
  });
});

describe("speaking while the reply is written (SpeechChunker)", () => {
  /** Feed `parts` one after another, as the stream would, then finish: every chunk, in order. */
  function stream(parts: string[]): { chunks: string[]; seqs: number[]; early: string[] } {
    const chunker = new SpeechChunker();
    let content = "";
    const all: { seq: number; text: string }[] = [];
    const early: string[] = [];
    for (const part of parts) {
      content += part;
      const ready = chunker.next(content);
      all.push(...ready);
      early.push(...ready.map((chunk) => chunk.text));
    }
    all.push(...chunker.finish(content));
    return { chunks: all.map((chunk) => chunk.text), seqs: all.map((chunk) => chunk.seq), early };
  }

  test("a finished sentence is spoken while the next is still arriving, and nothing twice", () => {
    const { chunks, seqs, early } = stream([
      "Photosynthesis is how green plants make food. ",
      "They use sun",
      "light and water. ",
      "Oxygen is given out.",
    ]);
    expect(early[0]).toBe("Photosynthesis is how green plants make food.");
    expect(chunks.join(" ")).toBe(
      "Photosynthesis is how green plants make food. They use sunlight and water. Oxygen is given out.",
    );
    expect(seqs).toEqual(seqs.map((_, index) => index));
  });

  test("never half a formula, half a code span, half a link or half a list item", () => {
    const parts = ["First, notice this. The answer is $x^", "2 + 1$. Done. See [the ", "book](https://x.test). End."];
    const { chunks } = stream(parts);
    expect(chunks.join(" ")).toBe("First, notice this. The answer is x squared plus 1. Done. See the book. End.");
    // A short step waits to join the next (MIN_CHUNK); a step's number is never cut from its words.
    const steps = stream(["1. Mix the flour well.\n2. Add wa", "ter slowly.\n3. Knead."]);
    expect(steps.early).toEqual(["1. Mix the flour well. 2. Add water slowly."]);
    expect(steps.chunks).toEqual(["1. Mix the flour well. 2. Add water slowly.", "3. Knead."]);
  });

  test("nothing inside a code fence, display maths or a table is spoken before it closes", () => {
    const { early, chunks } = stream([
      "Here is the program you need. ",
      "```py\nx = 1. y = 2. ",
      "print(x)\n```\n\nThat prints one.",
    ]);
    expect(early).toEqual(["Here is the program you need."]);
    expect(chunks.join(" ")).toBe(`Here is the program you need. ${NOTES.code} That prints one.`);
  });

  test("the first chunk may end at a comma, so the voice starts sooner", () => {
    const { early } = stream(["Photosynthesis, which happens in the leaves of green plants, is a pro"]);
    expect(early).toEqual(["Photosynthesis, which happens in the leaves of green plants,"]);
  });

  test("a reply that grows into several blocks is still spoken once, in order", () => {
    const text = "## Osmosis\n\nWater moves through a membrane. It goes from more to less water.\n\n- It needs no energy.\n- It is passive.";
    const { chunks } = stream(text.match(/.{1,7}/gs) ?? []);
    expect(chunks.join(" ")).toBe(speak(text).join(" "));
  });
});
