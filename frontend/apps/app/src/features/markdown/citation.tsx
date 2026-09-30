"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@v1/ui/tooltip";
import { FileText, Library } from "lucide-react";
import { useContext } from "react";

import type { Citation } from "@/lib/api/types";
import { CitationsContext } from "./context";

const CITED = /\[([Ff]?\d{1,2})\]/g;

/** The refs a reply cites in its prose (not inside code or maths), in order of first use. */
export function citedRefs(content: string): string[] {
  const prose = content
    .replace(/```[\s\S]*?(?:```|$)/g, " ")
    .replace(/`[^`\n]*`/g, " ")
    .replace(/\$\$[\s\S]*?\$\$/g, " ")
    .replace(/\$[^$\n]*\$/g, " ");
  return [...new Set([...prose.matchAll(CITED)].map((match) => (match[1] ?? "").toUpperCase()))];
}

/**
 * A `[1]` or `[F1]` marker (remark-tutor.ts). A chip naming its source when the reply's citations
 * know it; otherwise exactly the text the model wrote (a reply from before citations, a reply
 * still streaming, or a number that is not a citation at all).
 */
export function CitationMark({ cite }: { cite: string }) {
  const citation = useContext(CitationsContext)?.find((item) => item.ref === cite);
  if (!citation) return <>[{cite}]</>;
  const label = citation.kind === "file" ? `Your file: ${citation.title}` : `Source: ${citation.title}`;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`${cite}. ${label}`}
          className="focus-ring mx-0.5 inline-flex h-[1.35em] translate-y-[-0.1em] items-center rounded-md bg-brand-soft px-1.5 align-middle text-[0.75em] font-semibold leading-none text-brand"
        >
          {cite}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/** The sources a finished reply cites, under it: the phone's way to see what a chip names. */
export function Sources({ citations, content }: { citations: Citation[]; content: string }) {
  const cited = citedRefs(content);
  const shown = cited.flatMap((ref) => citations.filter((citation) => citation.ref === ref));
  if (!shown.length) return null;
  return (
    <div className="mt-3 border-t border-border pt-2 text-xs leading-5 text-text-secondary">
      <p className="font-semibold text-foreground">Sources</p>
      <ul className="mt-1 space-y-0.5">
        {shown.map((citation) => {
          const Icon = citation.kind === "file" ? FileText : Library;
          return (
            <li key={citation.ref} className="flex min-w-0 items-start gap-1.5">
              <span className="shrink-0 font-semibold text-brand">[{citation.ref}]</span>
              <Icon aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 break-words">
                {citation.kind === "file" ? "Your file: " : ""}
                {citation.title}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
