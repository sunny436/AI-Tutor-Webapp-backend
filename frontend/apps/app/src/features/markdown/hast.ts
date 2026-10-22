/**
 * Small helpers over the HTML syntax tree react-markdown renders from.
 * Written out rather than pulled in: they are a few lines each.
 */

export type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

/** The plain text of a subtree (what "copy code" should copy). */
export function hastText(node: HastNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(hastText).join("");
}

/**
 * Rehype plugin: mark `<code>` elements that sit inside `<pre>` as blocks.
 *
 * react-markdown renders block and inline code through the same `code`
 * component, and a fenced block without a language has no class to tell them
 * apart. Runs after the sanitizer, so the marker cannot come from content.
 */
export function rehypeMarkBlockCode() {
  return (tree: HastNode) => {
    const visit = (node: HastNode) => {
      if (node.type === "element" && node.tagName === "pre") {
        for (const child of node.children ?? []) {
          if (child.type === "element" && child.tagName === "code") {
            child.properties = { ...child.properties, dataBlock: "true" };
          }
        }
      }
      for (const child of node.children ?? []) visit(child);
    };
    visit(tree);
  };
}

/**
 * Rehype plugin: a display equation is a focusable, named region, as a table is
 * (`@v1/ui/table`). On a narrow screen a long one scrolls sideways
 * (markdown.css), and a scrollable region must be reachable by keyboard. Runs
 * after rehype-katex, so the marker cannot come from content.
 */
export function rehypeFocusableMaths() {
  return (tree: HastNode) => {
    const visit = (node: HastNode) => {
      const className = node.properties?.className;
      if (node.type === "element" && Array.isArray(className) && className.includes("katex-display")) {
        node.properties = { ...node.properties, className: [...className, "focus-ring"], tabIndex: 0, role: "region", ariaLabel: "Equation" };
        return;
      }
      for (const child of node.children ?? []) visit(child);
    };
    visit(tree);
  };
}

/**
 * Rehype plugin: show raw HTML from a reply as text instead of dropping it.
 *
 * Without `rehype-raw` the HTML is never parsed, but the sanitizer would delete
 * the unparsed nodes outright — so a reply explaining "use a `<div>`" outside a
 * code fence would lose words. Turning them into text keeps what the model wrote
 * (React escapes it) while running no markup. Runs before the sanitizer.
 */
export function rehypeRawAsText() {
  return (tree: HastNode) => {
    const visit = (node: HastNode) => {
      for (const child of node.children ?? []) {
        if (child.type === "raw") child.type = "text";
        else visit(child);
      }
    };
    visit(tree);
  };
}

/** `language-ts` → `ts`, from a className that may be a string or a list. */
export function languageOf(className: unknown): string | null {
  const classes = Array.isArray(className) ? className : String(className ?? "").split(/\s+/);
  for (const value of classes) {
    const match = /^language-(.+)$/.exec(String(value));
    if (match?.[1] && match[1] !== "math") return match[1];
  }
  return null;
}
