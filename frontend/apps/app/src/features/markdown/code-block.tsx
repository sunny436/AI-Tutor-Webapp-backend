"use client";

import { Check, Copy, Download, Terminal } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

/** Text types a download may be, by extension; anything else downloads as plain text. */
const MIME: Record<string, string> = {
  csv: "text/csv",
  tsv: "text/tab-separated-values",
  json: "application/json",
  md: "text/markdown",
  txt: "text/plain",
};

/** Saves `text` as a file of that name, made in the page: nothing is fetched or uploaded. */
function saveText(filename: string, text: string) {
  const extension = filename.split(".").pop()?.toLowerCase() ?? "";
  const blob = new Blob([text], { type: `${MIME[extension] ?? "text/plain"};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * A fenced code block: language label, horizontal scroll (never the page), and a
 * copy button that copies the raw code — not the highlighted markup. A block the
 * tutor named (```csv filename="marks.csv") can also be downloaded as that file;
 * program output (```output) is labelled as output rather than as a language.
 */
export function CodeBlock({
  language,
  text,
  filename,
  variant,
  children,
}: {
  language: string | null;
  text: string;
  filename?: string;
  variant?: "output";
  children: ReactNode;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const raw = text.replace(/\n$/, "");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(raw);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const output = variant === "output";
  const label = filename ?? (output ? "Output" : (language ?? "code"));

  return (
    <div className={`group/code my-3 overflow-hidden rounded-xl border border-border ${output ? "bg-surface-2" : "bg-surface"}`}>
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5 text-2xs text-text-secondary">
        <span className="flex min-w-0 items-center gap-1.5 font-mono">
          {output && <Terminal aria-hidden className="h-3.5 w-3.5 shrink-0" />}
          <span className="truncate">{label}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {filename && (
            <button
              type="button"
              onClick={() => saveText(filename, raw)}
              className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 transition-colors hover:bg-surface-2 hover:text-foreground"
              aria-label={`Download ${filename}`}
            >
              <Download aria-hidden className="h-3.5 w-3.5" />
              <span>Download</span>
            </button>
          )}
          <button
            type="button"
            onClick={copy}
            className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 transition-colors hover:bg-surface-2 hover:text-foreground"
            aria-label={copied ? "Code copied" : "Copy code"}
          >
            {copied ? <Check aria-hidden className="h-3.5 w-3.5" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>
        </span>
      </div>
      <pre
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard-focusable to be scrollable
        tabIndex={0}
        role="region"
        aria-label={output ? "Output" : language ? `${language} code` : "Code"}
        className="scrollbar-subtle focus-ring-inset overflow-x-auto p-3 text-sm leading-6"
      >
        {children}
      </pre>
    </div>
  );
}
