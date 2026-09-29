"use client";

import { Check, Copy } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

/**
 * A fenced code block: language label, horizontal scroll (never the page), and a
 * copy button that copies the raw code — not the highlighted markup.
 */
export function CodeBlock({
  language,
  text,
  children,
}: {
  language: string | null;
  text: string;
  children: ReactNode;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text.replace(/\n$/, ""));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="group/code my-3 overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5 text-2xs text-text-secondary">
        <span className="font-mono">{language ?? "code"}</span>
        <button
          type="button"
          onClick={copy}
          className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 transition-colors hover:bg-surface-2 hover:text-foreground"
          aria-label={copied ? "Code copied" : "Copy code"}
        >
          {copied ? <Check aria-hidden className="h-3.5 w-3.5" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <pre
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard-focusable to be scrollable
        tabIndex={0}
        role="region"
        aria-label={language ? `${language} code` : "Code"}
        className="scrollbar-subtle focus-ring-inset overflow-x-auto p-3 text-sm leading-6"
      >
        {children}
      </pre>
    </div>
  );
}
