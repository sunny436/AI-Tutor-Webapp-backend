import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { MessageContent } from "./message-content";

const render = (content: string) => renderToStaticMarkup(<MessageContent content={content} />);

describe("Markdown rendering", () => {
  test("paragraphs, emphasis and headings (shifted below the page's own)", () => {
    const html = render("# Title\n\nSome **bold** and *italic* text.\n\n## Sub");
    expect(html).toContain("<h3");
    expect(html).toContain("<h4");
    expect(html).not.toContain("<h1");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
  });

  test("lists and blockquotes", () => {
    const html = render("- one\n- two\n\n1. first\n2. second\n\n> quoted");
    expect(html).toContain("<ul");
    expect(html).toContain("<ol");
    expect(html.match(/<li/g)?.length).toBe(4);
    expect(html).toContain("<blockquote");
  });

  test("links open safely in a new tab", () => {
    const html = render("[docs](https://example.com/docs) and <https://auto.example.com>");
    expect(html).toContain('href="https://example.com/docs"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer nofollow"');
    expect(html).toContain('href="https://auto.example.com"');
  });

  test("GFM tables render as tables inside one focusable scroll container", () => {
    const html = render("| a | b |\n|---|---|\n| 1 | 2 |");
    expect(html).toContain("<table");
    expect(html).toContain("<th");
    expect(html).toContain("<td");
    // Keyboard users can scroll a wide table, and there is one scroller, not two.
    expect(html).toContain('tabindex="0" role="region" aria-label="Table"');
    expect(html.match(/overflow-x-auto/g)).toHaveLength(1);
  });

  test("fenced code: language label, highlighting and a copy button", () => {
    const html = render("```ts\nconst answer: number = 42;\n```");
    expect(html).toContain("<pre");
    expect(html).toContain("language-ts");
    expect(html).toContain("hljs");
    expect(html).toContain('aria-label="Copy code"');
    expect(html).toContain(">ts<");
    // A long line scrolls inside the block, so the block must take keyboard focus.
    expect(html).toContain('<pre tabindex="0" role="region" aria-label="ts code"');
  });

  test("a fence without a language is still a block, not inline code", () => {
    const html = render("```\nplain block\n```");
    expect(html).toContain("<pre");
    expect(html).toContain(">code<");
    expect(html).not.toContain("rounded-md bg-surface-2 px-1.5");
  });

  test("inline code is styled inline", () => {
    const html = render("Run `npm test` now.");
    expect(html).toContain("rounded-md bg-surface-2 px-1.5");
    expect(html).not.toContain("<pre");
  });

  test("inline and display maths render with KaTeX", () => {
    const inline = render("Euler: $e^{i\\pi} + 1 = 0$");
    expect(inline).toContain('class="katex"');
    expect(inline).not.toContain("katex-error");
    expect(inline).not.toContain("katex-display");
    const display = render("$$\n\\frac{a}{b}\n$$");
    expect(display).toContain("katex-display");
    expect(display).not.toContain("katex-error");
  });

  test("invalid maths does not break the reply", () => {
    const html = render("Bad: $\\frac{$ and after");
    expect(html).toContain("after");
  });
});

describe("safety", () => {
  test("raw HTML is shown as text, never as markup", () => {
    const html = render('Hello <script>alert(1)</script> <b>bold?</b> <img src=x onerror="alert(1)"> <iframe src="https://x"></iframe>');
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("<b>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("&lt;b&gt;bold?&lt;/b&gt;");
  });

  test("javascript:, data: and relative links lose their href", () => {
    for (const markdown of [
      "[x](javascript:alert(1))",
      "[x](JaVaScRiPt:alert(1))",
      "[x](data:text/html;base64,PHNjcmlwdD4=)",
      "[x](/settings)",
      "[x](vbscript:msgbox)",
    ]) {
      const html = render(markdown);
      expect(html).not.toContain("href=");
      expect(html.toLowerCase()).not.toContain("javascript:");
    }
  });

  test("mailto links are allowed", () => {
    expect(render("[mail](mailto:a@example.com)")).toContain('href="mailto:a@example.com"');
  });

  test("images become links; nothing is loaded", () => {
    const html = render("![a chart](https://tracker.example/pixel.png)");
    expect(html).not.toContain("<img");
    expect(html).toContain('href="https://tracker.example/pixel.png"');
    expect(html).toContain("[Image: a chart]");
  });

  test("KaTeX cannot create links or run macros that need trust", () => {
    const html = render("$\\href{javascript:alert(1)}{click}$ $\\url{javascript:alert(2)}$");
    expect(html).not.toContain("<a ");
    expect(html.toLowerCase()).not.toContain('href="javascript:');
  });

  test("attribute injection through code fence language is neutralised", () => {
    const html = render('```js" onmouseover="alert(1)\nx\n```');
    expect(html).not.toContain("onmouseover=");
  });
});
