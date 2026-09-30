/**
 * The tutor's study syntax, added to the one Markdown pipeline (message-content.tsx):
 *
 *   :::type[Title] … :::   a study card; `::::` for an outer card around another one
 *   > [!NOTE] …            GitHub's alert syntax, rendered as the matching card
 *   ::file{ref=F1}         an attached file; ::pdf{ref=F1 page=3} one page of an attached PDF
 *   [1] and [F1]           a citation of a numbered source or attached file
 *   ```csv filename="a.csv"  a code block the student can download
 *
 * Only the BLOCK-level directive syntax is registered. Text directives (`:name`) would fire on
 * every "a:b" ratio, "10:30" time or "Na:Cl" in ordinary prose, so they are never parsed.
 *
 * Everything here only names elements and properties (`data.hName`, `data.hProperties`); the
 * sanitizer (sanitize-schema.ts) still decides what survives, with a value allowlist for each.
 */

import { directive } from "micromark-extension-directive";
import { directiveFromMarkdown } from "mdast-util-directive";

export const CARD_TYPES = [
  "note",
  "important",
  "warning",
  "definition",
  "example",
  "steps",
  "answer",
  "takeaway",
  "formula",
] as const;
export type CardType = (typeof CARD_TYPES)[number];

/** Names a model reaches for that mean one of the cards. */
const CARD_ALIASES: Record<string, CardType> = {
  info: "note",
  tip: "takeaway",
  summary: "takeaway",
  key: "takeaway",
  caution: "warning",
  danger: "warning",
  solution: "steps",
  result: "answer",
  final: "answer",
};

/** GitHub alert keyword → card. */
const ALERTS: Record<string, CardType> = {
  NOTE: "note",
  TIP: "takeaway",
  IMPORTANT: "important",
  WARNING: "warning",
  CAUTION: "warning",
};

type MdNode = {
  type: string;
  name?: string;
  value?: string;
  lang?: string | null;
  meta?: string | null;
  attributes?: Record<string, string | null | undefined> | null;
  children?: MdNode[];
  data?: Record<string, unknown>;
  position?: { start: { offset?: number }; end: { offset?: number } };
};

type ProcessorData = { micromarkExtensions?: unknown[]; fromMarkdownExtensions?: unknown[] };

const REF = /^F?\d{1,2}$/;
const CITATION = /\[([Ff]?\d{1,2})\]/g;
const COLON_LINE = /^[ \t]*:{3,}[ \t]*$/gm;
const HAS_COLON_LINE = /^[ \t]*:{3,}[ \t]*$/m;
const SAFE_NAME = /^[\w .()+-]{1,100}\.[A-Za-z0-9]{1,8}$/;

export function cardType(name: string | undefined): CardType | null {
  const key = (name ?? "").toLowerCase();
  if ((CARD_TYPES as readonly string[]).includes(key)) return key as CardType;
  return CARD_ALIASES[key] ?? null;
}

/** `filename="notes.csv"` (or filename=notes.csv) from a fence's info string; null when absent or unsafe. */
export function fenceFilename(info: string | null | undefined): string | null {
  const match = /(?:^|\s)filename=(?:"([^"]*)"|'([^']*)'|(\S+))/.exec(info ?? "");
  const raw = (match?.[1] ?? match?.[2] ?? match?.[3] ?? "").trim();
  const base = raw.split(/[\\/]/).pop() ?? "";
  return SAFE_NAME.test(base) ? base : null;
}

/** A paragraph holding nothing but one `$$…$$` (written with two dollars on each side). */
function isDisplayMath(paragraph: MdNode, source: string): boolean {
  const parts = (paragraph.children ?? []).filter((part) => !(part.type === "text" && !(part.value ?? "").trim()));
  const only = parts.length === 1 ? parts[0] : undefined;
  const start = only?.position?.start.offset;
  const end = only?.position?.end.offset;
  if (only?.type !== "inlineMath" || start === undefined || end === undefined) return false;
  const raw = source.slice(start, end);
  return raw.startsWith("$$") && raw.endsWith("$$");
}

function text(value: string): MdNode {
  return { type: "text", value };
}

/** A GitHub alert: a blockquote whose first line is exactly `[!TYPE]`. Returns the card, and strips the marker. */
function alertCard(quote: MdNode): CardType | null {
  const first = quote.children?.[0];
  const lead = first?.type === "paragraph" ? first.children?.[0] : undefined;
  if (!lead || lead.type !== "text" || !lead.value) return null;
  const match = /^\[!([A-Za-z]+)\][ \t]*(?:\n|$)/.exec(lead.value);
  const card = match?.[1] ? ALERTS[match[1].toUpperCase()] : undefined;
  if (!match || !card || !first) return null;
  lead.value = lead.value.slice(match[0].length);
  if (!lead.value) first.children?.shift();
  if (!first.children?.length) quote.children?.shift();
  return card;
}

/** `[1]` / `[F1]` in a text node → text and citation nodes (rendered as <sup data-cite>). */
function splitCitations(node: MdNode): MdNode[] | null {
  const value = node.value ?? "";
  if (!value.includes("[")) return null;
  const parts: MdNode[] = [];
  let last = 0;
  for (const match of value.matchAll(CITATION)) {
    const index = match.index ?? 0;
    const ref = (match[1] ?? "").toUpperCase();
    if (index > last) parts.push(text(value.slice(last, index)));
    parts.push({
      type: "citation",
      data: { hName: "sup", hProperties: { dataCite: ref }, hChildren: [{ type: "text", value: `[${ref}]` }] },
    });
    last = index + match[0].length;
  }
  if (!parts.length) return null;
  if (last < value.length) parts.push(text(value.slice(last)));
  return parts;
}

export function remarkTutor(this: { data(): ProcessorData }) {
  const data = this.data();
  // Flow (block) constructs only: `:::card` containers and `::leaf` lines, never `:text`.
  data.micromarkExtensions = [...(data.micromarkExtensions ?? []), { flow: directive().flow }];
  data.fromMarkdownExtensions = [...(data.fromMarkdownExtensions ?? []), directiveFromMarkdown()];

  return (tree: MdNode, file: { value?: unknown }) => {
    const source = typeof file.value === "string" ? file.value : String(file.value ?? "");

    const visit = (node: MdNode, inLink: boolean) => {
      const children = node.children;
      if (!children) return;
      for (let index = 0; index < children.length; index++) {
        const child = children[index] as MdNode;

        if (child.type === "containerDirective") {
          const card = cardType(child.name);
          child.data = { ...child.data, hName: "div", hProperties: card ? { dataCard: card } : {} };
          const label = child.children?.[0];
          if (card && label?.data?.directiveLabel) {
            label.data = { ...label.data, hName: "div", hProperties: { dataCardTitle: "true" } };
          }
        } else if (child.type === "leafDirective") {
          const ref = String(child.attributes?.ref ?? "").toUpperCase();
          const page = String(child.attributes?.page ?? "");
          if ((child.name === "file" || child.name === "pdf") && REF.test(ref)) {
            child.data = {
              hName: "div",
              hProperties: { dataEmbed: child.name, dataRef: ref, ...(/^\d{1,4}$/.test(page) ? { dataPage: page } : {}) },
            };
            child.children = [];
          } else {
            // Not ours: show exactly what the model wrote.
            const start = child.position?.start.offset;
            const end = child.position?.end.offset;
            const raw = start !== undefined && end !== undefined ? source.slice(start, end) : `::${child.name ?? ""}`;
            children[index] = { type: "paragraph", children: [text(raw)] };
            continue;
          }
        } else if (child.type === "blockquote") {
          const card = alertCard(child);
          if (card) child.data = { ...child.data, hName: "div", hProperties: { dataCard: card } };
        } else if (child.type === "code") {
          let name = fenceFilename(child.meta);
          if (!name && !child.meta && child.lang?.startsWith("filename=")) {
            name = fenceFilename(child.lang);
            child.lang = null;
          }
          if (name) child.data = { ...child.data, hProperties: { dataFilename: name } };
        } else if (child.type === "paragraph" && isDisplayMath(child, source)) {
          // `$$ … $$` on one line, alone in its paragraph: the display equation the model meant
          // (the parser reads it as inline maths; only `$$` on lines of their own is a block).
          const value = child.children?.[0]?.value ?? "";
          children[index] = {
            type: "math",
            value,
            data: {
              hName: "pre",
              hChildren: [
                {
                  type: "element",
                  tagName: "code",
                  properties: { className: ["language-math", "math-display"] },
                  children: [{ type: "text", value }],
                },
              ],
            },
          };
          continue;
        } else if (child.type === "image" && inLink) {
          child.data = { ...child.data, hProperties: { dataInLink: "true" } };
        } else if (child.type === "paragraph" && child.children?.some((part) => HAS_COLON_LINE.test(part.value ?? ""))) {
          // A card closed early leaves its `:::` behind as text: never show it.
          for (const part of child.children) {
            if (part.type === "text" && part.value) {
              part.value = part.value.replace(COLON_LINE, "").replace(/\n{2,}/g, "\n");
            }
          }
          child.children = child.children.filter((part) => part.type !== "text" || (part.value ?? "").trim() !== "");
          if (!child.children.length) {
            children.splice(index, 1);
            index--;
            continue;
          }
        } else if (child.type === "text" && !inLink) {
          const parts = splitCitations(child);
          if (parts) {
            children.splice(index, 1, ...parts);
            index += parts.length - 1;
            continue;
          }
        }

        visit(child, inLink || child.type === "link" || child.type === "linkReference");
      }
    };
    visit(tree, false);
  };
}
