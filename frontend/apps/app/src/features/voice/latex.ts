/**
 * A LaTeX formula as spoken English, the way a teacher reads school maths aloud: what voice mode says for `$…$`
 * and `$$…$$` in a reply (speech-text.ts).
 *
 * PARSED, NOT REPLACED. The formula is tokenized and read as a tree, so `\frac{a+b}{2}` and `x^{n+1}` keep their
 * structure however deeply they nest. Every number is said exactly as written (digits, decimal point, sign);
 * brackets that change the meaning are said ("the quantity …"); an unknown command is said by its name and
 * nothing is ever dropped. The formula itself stays in the chat as written.
 */

type Token = { kind: "command" | "char" | "open" | "close"; value: string };

/** A formula's tokens: `\name` commands, single characters, and braces. Spaces are separators only. */
function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;
  while (index < source.length) {
    const char = source[index] as string;
    if (char === "\\") {
      const name = /^\\([A-Za-z]+|.)/.exec(source.slice(index));
      const value = name?.[1] ?? "";
      tokens.push({ kind: "command", value });
      index += 1 + value.length;
    } else if (char === "{") {
      tokens.push({ kind: "open", value: char });
      index += 1;
    } else if (char === "}") {
      tokens.push({ kind: "close", value: char });
      index += 1;
    } else if (/\s/.test(char)) {
      index += 1;
    } else {
      tokens.push({ kind: "char", value: char });
      index += 1;
    }
  }
  return tokens;
}

type Node =
  | { kind: "number"; value: string }
  | { kind: "word"; value: string }
  | { kind: "op"; value: string }
  | { kind: "group"; items: Node[]; brackets?: "()" | "[]" | "||" }
  | { kind: "power"; base: Node; exponent: Node }
  | { kind: "sub"; base: Node; index: Node }
  | { kind: "frac"; top: Node; bottom: Node }
  | { kind: "root"; degree: Node | null; body: Node }
  | { kind: "text"; value: string }
  | { kind: "chem"; value: string };

const SPOKEN_COMMANDS: Record<string, string> = {
  times: "times",
  cdot: "times",
  div: "divided by",
  pm: "plus or minus",
  mp: "minus or plus",
  neq: "is not equal to",
  ne: "is not equal to",
  le: "is less than or equal to",
  leq: "is less than or equal to",
  ge: "is greater than or equal to",
  geq: "is greater than or equal to",
  approx: "is approximately",
  sim: "is similar to",
  equiv: "is equivalent to",
  propto: "is proportional to",
  to: "tends to",
  rightarrow: "gives",
  longrightarrow: "gives",
  Rightarrow: "implies",
  leftrightarrow: "is in equilibrium with",
  rightleftharpoons: "is in equilibrium with",
  infty: "infinity",
  sum: "the sum of",
  int: "the integral of",
  lim: "the limit",
  partial: "partial",
  nabla: "del",
  sin: "sine",
  cos: "cos",
  tan: "tan",
  cot: "cot",
  sec: "sec",
  csc: "cosec",
  log: "log",
  ln: "natural log",
  exp: "exp",
  degree: "degrees",
  circ: "degrees",
  angle: "angle",
  triangle: "triangle",
  perp: "is perpendicular to",
  parallel: "is parallel to",
  therefore: "therefore",
  because: "because",
  in: "in",
  "%": "percent",
  ldots: "and so on",
  dots: "and so on",
  cdots: "and so on",
};
const GREEK = new Set(
  "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho sigma tau upsilon phi varphi chi psi omega"
    .split(" ")
    .flatMap((name) => [name, name[0]?.toUpperCase() + name.slice(1)]),
);
const SPACES = new Set([",", ";", "!", " ", ":", "quad", "qquad", "enspace", "thinspace"]);
const IGNORED = new Set(["left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "textstyle", "limits", "nolimits"]);
// Real text, read as written; styled maths (\mathrm{CO_2}) is read as maths.
const TEXT = new Set(["text", "textbf", "textit", "textrm", "operatorname", "mbox"]);
const STYLE = new Set(["mathrm", "mathbf", "mathit", "mathsf", "mathcal", "boldsymbol", "bm", "vec", "overline", "hat"]);
const OPERATORS: Record<string, string> = {
  "+": "plus",
  "-": "minus",
  "=": "equals",
  "<": "is less than",
  ">": "is greater than",
  "/": "divided by",
  "*": "times",
  ",": ",",
  "!": "factorial",
  "'": "prime",
  "%": "percent",
  ":": "is to",
  "|": "|",
};

class Parser {
  private position = 0;
  constructor(private readonly tokens: Token[]) {}

  /** A run of items up to a closing brace (or the end), with powers and subscripts attached. At the top level a
   * stray closing brace is skipped, so the rest is still read. */
  sequence(until?: string, top = false): Node[] {
    const items: Node[] = [];
    while (this.position < this.tokens.length) {
      const token = this.tokens[this.position] as Token;
      if (token.kind === "close" && top) {
        this.position += 1;
        continue;
      }
      if (token.kind === "close" || (until && token.kind === "char" && token.value === until)) break;
      const atom = this.atom();
      if (atom) items.push(this.postfix(atom));
    }
    return items;
  }

  private peek(): Token | undefined {
    return this.tokens[this.position];
  }

  private postfix(base: Node): Node {
    let node = base;
    for (;;) {
      const token = this.peek();
      if (token?.kind === "char" && token.value === "^") {
        this.position += 1;
        node = { kind: "power", base: node, exponent: this.argument() };
      } else if (token?.kind === "char" && token.value === "_") {
        this.position += 1;
        node = { kind: "sub", base: node, index: this.argument() };
      } else if (token?.kind === "char" && token.value === "'") {
        this.position += 1;
        node = { kind: "group", items: [node, { kind: "op", value: "'" }] };
      } else {
        return node;
      }
    }
  }

  /** One argument: a braced group, or a single atom (`x^2`, `\frac12`). */
  private argument(): Node {
    const token = this.peek();
    if (token?.kind === "open") {
      this.position += 1;
      const items = this.sequence();
      if (this.peek()?.kind === "close") this.position += 1;
      return { kind: "group", items };
    }
    if (token?.kind === "char" && /\d/.test(token.value)) {
      this.position += 1; // `x^23` is x squared then 3 in LaTeX: one digit only
      return { kind: "number", value: token.value };
    }
    return this.atom() ?? { kind: "group", items: [] };
  }

  /** The raw characters of a braced group, for \text{} and \ce{}. */
  private rawGroup(): string {
    if (this.peek()?.kind !== "open") return this.argumentText();
    this.position += 1;
    let depth = 1;
    let text = "";
    while (this.position < this.tokens.length) {
      const token = this.tokens[this.position] as Token;
      this.position += 1;
      if (token.kind === "open") depth += 1;
      if (token.kind === "close" && --depth === 0) break;
      text += token.kind === "command" ? ` ${token.value} ` : token.value;
    }
    return text;
  }

  private argumentText(): string {
    const token = this.peek();
    if (!token) return "";
    this.position += 1;
    return token.value;
  }

  private atom(): Node | null {
    const token = this.peek();
    if (!token) return null;
    if (token.kind === "open") {
      this.position += 1;
      const items = this.sequence();
      if (this.peek()?.kind === "close") this.position += 1;
      return { kind: "group", items };
    }
    if (token.kind === "close") {
      this.position += 1;
      return null;
    }
    if (token.kind === "command") {
      this.position += 1;
      const name = token.value;
      if (name === "frac" || name === "dfrac" || name === "tfrac") {
        return { kind: "frac", top: this.argument(), bottom: this.argument() };
      }
      if (name === "sqrt") {
        let degree: Node | null = null;
        if (this.peek()?.kind === "char" && this.peek()?.value === "[") {
          this.position += 1;
          degree = { kind: "group", items: this.sequence("]") };
          if (this.peek()?.value === "]") this.position += 1;
        }
        return { kind: "root", degree, body: this.argument() };
      }
      if (name === "ce") return { kind: "chem", value: this.rawGroup() };
      if (TEXT.has(name)) return { kind: "text", value: this.rawGroup() };
      if (STYLE.has(name)) return this.argument();
      if (IGNORED.has(name) || SPACES.has(name)) return null;
      if (name === "\\") return { kind: "op", value: "," };
      if (name === "{" || name === "}" || name === "|") return null;
      if (GREEK.has(name)) return { kind: "word", value: name.toLowerCase() };
      if (SPOKEN_COMMANDS[name]) return { kind: "word", value: SPOKEN_COMMANDS[name] as string };
      return { kind: "word", value: name }; // unknown: said by its name, never dropped
    }
    // A character.
    this.position += 1;
    const char = token.value;
    if (/\d/.test(char) || (char === "." && /\d/.test(this.peek()?.value ?? ""))) {
      let number = char;
      while (/^[\d.]$/.test(this.peek()?.value ?? "") && this.peek()?.kind === "char") {
        const next = this.peek()?.value as string;
        if (next === "." && !/\d/.test(this.tokens[this.position + 1]?.value ?? "")) break;
        number += next;
        this.position += 1;
      }
      return { kind: "number", value: number };
    }
    if (char === "(" || char === "[") {
      const close = char === "(" ? ")" : "]";
      const items = this.sequence(close);
      if (this.peek()?.value === close) this.position += 1;
      return { kind: "group", items, brackets: char === "(" ? "()" : "[]" };
    }
    if (char === ")" || char === "]") return null;
    if (/[A-Za-z]/.test(char)) {
      let word = char;
      while (/^[A-Za-z]$/.test(this.peek()?.value ?? "") && this.peek()?.kind === "char") {
        word += this.peek()?.value;
        this.position += 1;
      }
      return { kind: "word", value: word };
    }
    if (OPERATORS[char]) return { kind: "op", value: char };
    return { kind: "word", value: char };
  }
}

/** H2O → "H 2 O", CO2 → "C O 2": element symbols and counts said one by one. */
function spellFormula(text: string): string {
  return text
    .replace(/->|→/g, " gives ")
    .replace(/<=>|⇌/g, " is in equilibrium with ")
    .replace(/\+/g, " plus ")
    .replace(/([A-Z][a-z]?|\d+(?:\.\d+)?)/g, " $1 ")
    .replace(/\s+/g, " ")
    .trim();
}

function isSimple(node: Node): boolean {
  if (node.kind === "number" || node.kind === "word") return true;
  return node.kind === "group" && !node.brackets && node.items.length === 1 && isSimple(node.items[0] as Node);
}

function say(node: Node): string {
  switch (node.kind) {
    case "number":
    case "word":
      return node.value;
    case "text":
      return node.value.trim();
    case "chem":
      return spellFormula(node.value);
    case "op":
      return OPERATORS[node.value] ?? node.value;
    case "frac":
      return isSimple(node.top) && isSimple(node.bottom)
        ? `${say(node.top)} over ${say(node.bottom)}`
        : `the fraction ${say(node.top)}, over ${say(node.bottom)},`;
    case "root": {
      const degree = node.degree ? say(node.degree) : "";
      const which = degree === "" || degree === "2" ? "square root" : degree === "3" ? "cube root" : `root ${degree}`;
      return `the ${which} of ${say(node.body)}`;
    }
    case "power": {
      const exponent = say(node.exponent);
      const base = node.base.kind === "group" && node.base.brackets ? `the quantity ${sayItems(node.base.items)},` : say(node.base);
      if (exponent === "2") return `${base} squared`;
      if (exponent === "3") return `${base} cubed`;
      if (exponent === "degrees" || exponent === "circ") return `${base} degrees`;
      return isSimple(node.exponent) ? `${base} to the power ${exponent}` : `${base} to the power ${exponent},`;
    }
    case "sub":
      return `${say(node.base)} ${say(node.index)}`;
    case "group": {
      const inner = sayItems(node.items);
      if (node.brackets === "()") return `the quantity ${inner},`;
      return inner;
    }
  }
}

function sayItems(items: Node[]): string {
  const words: string[] = [];
  items.forEach((item, index) => {
    const previous = items[index - 1];
    // 2(x + 3): two times the quantity, never "2 x plus 3".
    if (item.kind === "group" && item.brackets === "()" && previous && previous.kind === "number") words.push("times");
    // f(x): f of x.
    if (item.kind === "group" && item.brackets === "()" && previous?.kind === "word" && previous.value.length === 1) {
      words.push(`of ${sayItems(item.items)}`);
      return;
    }
    words.push(say(item));
  });
  return words
    .join(" ")
    .replace(/\s+,/g, ",")
    .replace(/,+/g, ",")
    .replace(/\s+/g, " ")
    .trim();
}

export function speakLatex(source: string): string {
  const spoken = sayItems(new Parser(tokenize(source)).sequence(undefined, true));
  return spoken.replace(/^,\s*/, "").replace(/,$/, "");
}
