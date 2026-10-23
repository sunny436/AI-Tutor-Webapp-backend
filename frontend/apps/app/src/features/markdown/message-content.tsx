/**
 * Renders a reply's Markdown — the model's raw output — safely.
 *
 *   remark-gfm      tables, strikethrough (~~double~~ only), task lists, autolinks
 *   remark-math     $inline$ and $$display$$ maths
 *   remark-tutor    study cards, GitHub alerts, file embeds, citations, download names
 *   rehype-sanitize GitHub-style allowlist (see sanitize-schema.ts) — runs FIRST
 *   rehype-katex    maths → KaTeX markup (trust off, size/expansion capped), with mhchem
 *                   (\ce chemistry, \pu units)
 *   rehype-highlight syntax colours for fenced blocks with a language
 *
 * Raw HTML in a reply is not parsed (no rehype-raw): it is shown as text.
 *
 * A reply renders as its top-level blocks (blocks.ts), each parsed once and kept while later
 * ones arrive: while a reply streams only its last block is parsed again, and the finished reply
 * is the same elements as the streaming one, so nothing is replaced when it completes.
 *
 * EXTENSION POINT. `components` below is the single place that decides how each element
 * renders: study cards (`div[data-card]`), file embeds (`div[data-embed]`), citations
 * (`sup[data-cite]`), and fenced blocks the tutor draws instead of printing (rich-block.tsx:
 * mermaid, chart and the practice widgets). New content types are added there, or as an entry
 * in remark-tutor.ts feeding one, without touching the pipeline or the chat.
 *
 * The KaTeX and highlight stylesheets are loaded by the app layout, not here, so
 * this module stays importable in unit tests.
 */

import "katex/contrib/mhchem";
import { Image as ImageIcon } from "lucide-react";
import { Fragment, memo, useEffect, useRef, useState } from "react";
import type { ComponentPropsWithoutRef, JSX, ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import type { Citation } from "@/lib/api/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@v1/ui/table";
import { splitBlocks, streamSafe } from "./blocks";
import { CitationMark, Sources } from "./citation";
import { CodeBlock } from "./code-block";
import { CitationsContext, LiveContext, TestContext, type TestState } from "./context";
import { FileEmbed } from "./file-embed";
import { type HastNode, hastText, languageOf, rehypeFocusableMaths, rehypeMarkBlockCode, rehypeRawAsText } from "./hast";
import { remarkTutor } from "./remark-tutor";
import { RichBlock, isRichLanguage } from "./rich-block";
import { safeUrl, sanitizeSchema } from "./sanitize-schema";
import { StudyCard } from "./study-card";

type Plugins = NonNullable<ComponentPropsWithoutRef<typeof ReactMarkdown>["remarkPlugins"]>;

// Single tildes stay text: "H~2~O" is a subscript someone meant, never a strike-through.
const remarkPlugins = [[remarkGfm, { singleTilde: false }], remarkMath, remarkTutor] as Plugins;
const rehypePlugins = [
  rehypeRawAsText,
  [rehypeSanitize, sanitizeSchema],
  rehypeMarkBlockCode,
  [
    rehypeKatex,
    {
      throwOnError: false,
      strict: "ignore",
      trust: false,
      // A reply cannot make the page allocate a giant box or loop macros. (mhchem's \ce expands
      // into a few dozen macros per reaction, well inside this.)
      maxSize: 20,
      maxExpand: 1000,
    },
  ],
  rehypeFocusableMaths,
  // Program output is shown as it was printed, never coloured as a shell session.
  [rehypeHighlight, { detect: false, plainText: ["output", "console", "stdout", "terminal"] }],
] as Plugins;

const OUTPUT_LANGUAGES = new Set(["output", "console", "stdout", "terminal"]);

type WithNode<T extends keyof JSX.IntrinsicElements> = ComponentPropsWithoutRef<T> & { node?: HastNode };

function Link({ href, children }: WithNode<"a">) {
  if (!href) return <span>{children}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="font-medium text-brand underline decoration-brand/40 underline-offset-2 transition-colors hover:decoration-brand"
    >
      {children}
    </a>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

/**
 * Images are shown as a captioned placeholder with a link, never loaded. A reply that embeds
 * an image would otherwise make every reader's browser fetch a third-party URL the moment it
 * rendered — a tracking pixel for free (and the page's CSP allows only its own images).
 */
function Image({ node, src, alt, title }: WithNode<"img">) {
  const url = typeof src === "string" ? safeUrl(src) : undefined;
  const label = alt?.trim() ? `Image: ${alt}` : "Image";
  const inLink = node?.properties?.dataInLink === "true";
  const caption = typeof title === "string" && title.trim() ? title.trim() : null;
  const host = url ? hostOf(url) : "";
  return (
    <span
      role="figure"
      aria-label={caption ?? alt?.trim() ?? "Image"}
      className="my-2 block max-w-full rounded-xl border border-border bg-surface px-3 py-2"
    >
      <span className="flex min-w-0 items-start gap-2">
        <ImageIcon aria-hidden className="mt-1 h-4 w-4 shrink-0 text-text-secondary" />
        <span className="min-w-0 break-words">
          {url && !inLink ? <Link href={url}>[{label}]</Link> : <span className="text-text-secondary">[{label}]</span>}
          {host ? <span className="ml-1.5 text-2xs text-text-secondary">{host}</span> : null}
        </span>
      </span>
      {caption ? <span className="mt-1 block break-words text-xs text-text-secondary">{caption}</span> : null}
    </span>
  );
}

function Code({ node, className, children }: WithNode<"code">) {
  if (node?.properties?.dataBlock) {
    return <code className={className}>{children}</code>;
  }
  return (
    <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.875em] text-foreground">{children}</code>
  );
}

function Pre({ node, children }: WithNode<"pre">) {
  const code = node?.children?.find((child) => child.type === "element" && child.tagName === "code");
  const language = languageOf(code?.properties?.className);
  const text = hastText(code);
  const filename = typeof code?.properties?.dataFilename === "string" ? code.properties.dataFilename : undefined;
  const block = (
    <CodeBlock
      language={language}
      text={text}
      filename={filename}
      variant={language && OUTPUT_LANGUAGES.has(language) ? "output" : undefined}
    >
      {children}
    </CodeBlock>
  );
  if (isRichLanguage(language)) return <RichBlock key={text} language={language} source={text} fallback={block} />;
  return block;
}

/** Study cards and file embeds (remark-tutor.ts); any other div is just a div. */
function Div({ node, children }: WithNode<"div">) {
  const properties = node?.properties ?? {};
  if (typeof properties.dataCard === "string") {
    return <StudyCard type={properties.dataCard as Parameters<typeof StudyCard>[0]["type"]}>{children}</StudyCard>;
  }
  if (typeof properties.dataEmbed === "string" && typeof properties.dataRef === "string") {
    return (
      <FileEmbed
        kind={properties.dataEmbed === "pdf" ? "pdf" : "file"}
        fileRef={properties.dataRef}
        page={typeof properties.dataPage === "string" ? Number(properties.dataPage) : undefined}
      />
    );
  }
  return <div>{children}</div>;
}

/** Citations; any other superscript (a GFM footnote mark) stays a superscript. */
function Sup({ node, children }: WithNode<"sup">) {
  const cite = node?.properties?.dataCite;
  if (typeof cite === "string") return <CitationMark cite={cite} />;
  return <sup>{children}</sup>;
}

const heading =
  (Tag: "h3" | "h4" | "h5" | "h6", className: string) =>
  ({ children }: { children?: ReactNode }) => <Tag className={className}>{children}</Tag>;

/**
 * Heading levels shift down: the page owns `h1`/`h2`, so a reply's `# Title`
 * becomes an `h3` and the document outline stays sane for screen readers.
 */
const components: Components = {
  h1: heading("h3", "mb-2 mt-6 text-[1.375rem] font-semibold leading-[1.3] text-foreground first:mt-0 sm:text-2xl"),
  h2: heading("h4", "mb-2 mt-5 text-[1.1875rem] font-semibold leading-[1.35] text-foreground first:mt-0 sm:text-xl"),
  h3: heading("h5", "mb-1.5 mt-4 text-lg font-semibold text-foreground first:mt-0"),
  h4: heading("h6", "mb-1 mt-3 text-base font-semibold text-foreground first:mt-0"),
  h5: heading("h6", "mb-1 mt-3 text-base font-semibold text-foreground first:mt-0"),
  h6: heading("h6", "mb-1 mt-3 text-base font-semibold text-text-secondary first:mt-0"),
  p: ({ children }) => <p className="my-3 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children, className }) => (
    <ul className={`my-3 space-y-1 pl-6 ${className?.includes("contains-task-list") ? "list-none pl-1" : "list-disc"}`}>
      {children}
    </ul>
  ),
  ol: ({ children, start }) => (
    <ol start={start} className="my-3 list-decimal space-y-1 pl-6">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-1 marker:text-text-secondary">{children}</li>,
  a: Link,
  img: Image,
  code: Code,
  pre: Pre,
  div: Div,
  sup: Sup,
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-border pl-4 text-text-secondary">{children}</blockquote>
  ),
  hr: () => <hr className="my-6 border-border" />,
  // Table scrolls sideways inside its own focusable, bordered region.
  table: ({ children }) => (
    <div className="my-3">
      <Table label="Table" className="min-w-full text-sm">
        {children}
      </Table>
    </div>
  ),
  thead: ({ children }) => <TableHeader>{children}</TableHeader>,
  tbody: ({ children }) => <TableBody>{children}</TableBody>,
  tr: ({ children }) => <TableRow>{children}</TableRow>,
  th: ({ children, style }) => (
    <TableHead style={style} className="whitespace-nowrap">
      {children}
    </TableHead>
  ),
  td: ({ children, style }) => <TableCell style={style}>{children}</TableCell>,
  input: ({ type, checked }) =>
    type === "checkbox" ? (
      <input type="checkbox" checked={Boolean(checked)} disabled readOnly className="mr-1.5 align-middle" />
    ) : null,
};

const urlTransform = (url: string) => safeUrl(url) ?? "";

/** One block of Markdown, parsed again only when its own text changes. */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components} urlTransform={urlTransform}>
      {text}
    </ReactMarkdown>
  );
});

/** Everything that is not phrasing content: kept out of labels, buttons and inline answers. */
const NOT_INLINE = [
  "p",
  "div",
  "pre",
  "ul",
  "ol",
  "li",
  "blockquote",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "a",
  "img",
  "input",
  "section",
  "sup",
];

/**
 * A short piece of Markdown (a quiz option, a flashcard face) through the same pipeline, as
 * phrasing only: bold, italic, code and maths, never a block, link or control inside a control.
 */
export const InlineMarkdown = memo(function InlineMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={{ code: Code }}
      urlTransform={urlTransform}
      disallowedElements={NOT_INLINE}
      unwrapDisallowed
    >
      {text}
    </ReactMarkdown>
  );
});

/**
 * The streaming last block as it should be parsed now. A long one (a table, a code block, a long list)
 * is parsed again every 100-300 ms by its length instead of at every reveal tick (~50 ms): each parse
 * redoes the whole block, and on a slow phone (CPU 4x) the parses kept typing waiting (2026-10-23).
 * A short block, and every block once the reply has finished, is the text itself.
 */
function useStreamingBlock(block: string, live: boolean): string {
  const every = block.length < 1000 ? 0 : block.length < 2000 ? 100 : block.length < 3000 ? 200 : 300;
  const slow = live && every > 0;
  const [shown, setShown] = useState(block);
  const latest = useRef(block);
  latest.current = block;
  useEffect(() => {
    if (!slow) return;
    setShown(latest.current);
    const timer = setInterval(() => setShown(latest.current), every);
    return () => clearInterval(timer);
  }, [slow, every]);
  return slow ? shown : block;
}

function MessageContentImpl({
  content,
  streaming = false,
  citations,
  tests = null,
}: {
  content: string;
  streaming?: boolean;
  citations?: Citation[];
  /** The reply's practice test as the server recorded it (features/chat/message.tsx). */
  tests?: TestState | null;
}) {
  const blocks = splitBlocks(content);
  const last = blocks.length - 1;
  const tail = useStreamingBlock(blocks[last] ?? "", streaming);
  return (
    <CitationsContext.Provider value={citations}>
      <TestContext.Provider value={tests}>
        <div className="message-content min-w-0 break-words text-base text-foreground">
          {blocks.map((block, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: blocks only grow at the end, so a block keeps its place
            <Fragment key={index}>
              {/* The same line break the parser puts between top-level elements: identical HTML. */}
              {index > 0 && "\n"}
              <LiveContext.Provider value={streaming && index === last}>
                <Markdown text={streaming && index === last ? streamSafe(tail) : block} />
              </LiveContext.Provider>
            </Fragment>
          ))}
          {citations && !streaming ? <Sources citations={citations} content={content} /> : null}
        </div>
      </TestContext.Provider>
    </CitationsContext.Provider>
  );
}

/** Re-renders only when the text changes (finished replies never re-parse). */
export const MessageContent = memo(MessageContentImpl);
