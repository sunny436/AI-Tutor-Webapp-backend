/**
 * Renders a reply's Markdown — the model's raw output — safely.
 *
 *   remark-gfm      tables, strikethrough, task lists, autolinks
 *   remark-math     $inline$ and $$display$$ maths
 *   rehype-sanitize GitHub-style allowlist (see sanitize-schema.ts) — runs FIRST
 *   rehype-katex    maths → KaTeX markup (trust off, size/expansion capped)
 *   rehype-highlight syntax colours for fenced blocks with a language
 *
 * Raw HTML in a reply is not parsed (no rehype-raw): it is shown as text.
 *
 * EXTENSION POINT. `components` below is the single place that decides how each
 * element renders. Future content types — citations, diagrams (```mermaid),
 * chemistry, educational blocks — are added as entries here (or as an extra remark
 * plugin feeding one), without touching the pipeline or the chat. None exist yet.
 *
 * The KaTeX and highlight stylesheets are loaded by the app layout, not here, so
 * this module stays importable in unit tests.
 */

import { memo } from "react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@v1/ui/table";
import { CodeBlock } from "./code-block";
import { type HastNode, hastText, languageOf, rehypeMarkBlockCode, rehypeRawAsText } from "./hast";
import { safeUrl, sanitizeSchema } from "./sanitize-schema";

const remarkPlugins = [remarkGfm, remarkMath];
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
      // A reply cannot make the page allocate a giant box or loop macros.
      maxSize: 20,
      maxExpand: 500,
    },
  ],
  [rehypeHighlight, { detect: false }],
] as NonNullable<ComponentPropsWithoutRef<typeof ReactMarkdown>["rehypePlugins"]>;

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

/**
 * Images are shown as links, not loaded. A reply that embeds an image would
 * otherwise make every reader's browser fetch a third-party URL the moment it
 * rendered — a tracking pixel for free.
 */
function Image({ src, alt }: WithNode<"img">) {
  const url = typeof src === "string" ? safeUrl(src) : undefined;
  const label = alt?.trim() ? `Image: ${alt}` : "Image";
  if (!url) return <span className="text-text-secondary">[{label}]</span>;
  return <Link href={url}>[{label}]</Link>;
}

function Code({ node, className, children }: WithNode<"code">) {
  if (node?.properties?.dataBlock) {
    return <code className={className}>{children}</code>;
  }
  return (
    <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.875em] text-foreground">
      {children}
    </code>
  );
}

function Pre({ node, children }: WithNode<"pre">) {
  const code = node?.children?.find((child) => child.type === "element" && child.tagName === "code");
  return (
    <CodeBlock language={languageOf(code?.properties?.className)} text={hastText(code)}>
      {children}
    </CodeBlock>
  );
}

const heading =
  (Tag: "h3" | "h4" | "h5" | "h6", className: string) =>
  ({ children }: { children?: ReactNode }) => <Tag className={className}>{children}</Tag>;

/**
 * Heading levels shift down: the page owns `h1`/`h2`, so a reply's `# Title`
 * becomes an `h3` and the document outline stays sane for screen readers.
 */
const components: Components = {
  h1: heading("h3", "mb-2 mt-5 text-lg font-semibold text-foreground first:mt-0"),
  h2: heading("h4", "mb-2 mt-5 text-base font-semibold text-foreground first:mt-0"),
  h3: heading("h5", "mb-1.5 mt-4 text-[0.9375rem] font-semibold text-foreground first:mt-0"),
  h4: heading("h6", "mb-1 mt-3 text-sm font-semibold text-foreground first:mt-0"),
  h5: heading("h6", "mb-1 mt-3 text-sm font-semibold text-foreground first:mt-0"),
  h6: heading("h6", "mb-1 mt-3 text-sm font-semibold text-text-secondary first:mt-0"),
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
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-border pl-4 text-text-secondary">{children}</blockquote>
  ),
  hr: () => <hr className="my-6 border-border" />,
  table: ({ children }) => (
    <div className="scrollbar-subtle my-3 overflow-x-auto rounded-xl border border-border">
      <Table className="min-w-full text-sm">{children}</Table>
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

function MessageContentImpl({ content }: { content: string }) {
  return (
    <div className="message-content min-w-0 break-words text-[0.9375rem] leading-7 text-foreground">
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
        urlTransform={(url) => safeUrl(url) ?? ""}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

/** Re-renders only when the text changes (finished replies never re-parse). */
export const MessageContent = memo(MessageContentImpl);
