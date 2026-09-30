/**
 * What the Markdown renderer lets through.
 *
 * Starts from GitHub's sanitisation rules (`hast-util-sanitize` default schema)
 * and narrows it:
 *
 *   - links: `http`, `https` and `mailto` only (no `irc`, `xmpp`, `javascript:` …)
 *   - code:  `language-*` classes, plus the two `remark-math` markers
 *            (`math-inline` / `math-display`) KaTeX uses to tell inline from display
 *
 * and admits the tutor's own elements (remark-tutor.ts), each property with an allowlist of
 * values: study cards (`div[data-card]`, a title `div[data-card-title]`), file embeds
 * (`div[data-embed][data-ref][data-page]`), citations (`sup[data-cite]`), a download name
 * (`code[data-filename]`) and images inside links (`img[data-in-link]`).
 *
 * The sanitizer runs BEFORE KaTeX and the syntax highlighter, so their generated
 * markup (which the sanitizer would otherwise strip) is added after the content
 * has been cleaned. Raw HTML in a reply is never parsed at all (no `rehype-raw`),
 * so it renders as text.
 */

import type { Options as SanitizeSchema } from "rehype-sanitize";
import { defaultSchema } from "rehype-sanitize";

import { CARD_TYPES } from "./remark-tutor";

const REF = /^F?\d{1,2}$/;

export const sanitizeSchema: SanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [
      ["className", /^language-[\w#+.-]+$/, "math-inline", "math-display"],
      ["dataFilename", /^[\w .()+-]{1,100}\.[A-Za-z0-9]{1,8}$/],
    ],
    div: [
      ...(defaultSchema.attributes?.div ?? []),
      ["dataCard", ...CARD_TYPES],
      ["dataCardTitle", "true"],
      ["dataEmbed", "file", "pdf"],
      ["dataRef", REF],
      ["dataPage", /^\d{1,4}$/],
    ],
    sup: [...(defaultSchema.attributes?.sup ?? []), ["dataCite", REF]],
    img: [...(defaultSchema.attributes?.img ?? []), ["dataInLink", "true"]],
  },
  protocols: {
    ...defaultSchema.protocols,
    href: ["http", "https", "mailto"],
    src: ["http", "https"],
  },
};

/**
 * `urlTransform` for react-markdown: absolute http(s) and mailto only. Relative
 * links in a model's reply would navigate inside this app, which is never what
 * the model meant, so they are dropped too.
 */
export function safeUrl(url: string): string | undefined {
  const value = url.trim();
  if (/^https?:\/\//i.test(value)) return value;
  if (/^mailto:/i.test(value)) return value;
  return undefined;
}
