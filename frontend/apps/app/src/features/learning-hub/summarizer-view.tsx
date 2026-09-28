import { Button } from "@v1/ui/button";
import { Lightbulb } from "lucide-react";

import { PreviewBadge } from "@/components/preview-badge";
import { SUMMARY_EXAMPLE } from "./demo-data";
import { SoonLabel, ToolPage } from "./tool-page";

/** Summarizer (preview): the input, and one summary of the kind it would make. */
export function SummarizerView() {
  return (
    <ToolPage label="Summarizer">
      <section className="space-y-4 rounded-2xl border border-border bg-card p-5 elev-1 sm:p-6">
        <div>
          <h2 className="text-lg font-bold text-foreground">Chapter Summarizer</h2>
          <p className="mt-1 text-xs text-text-secondary">
            Paste long textbook paragraphs or select a chapter from NCERT to get a 2-minute bullet summary.
          </p>
        </div>
        <label htmlFor="summarize-text" className="sr-only">
          Text or chapter name to summarise
        </label>
        <textarea
          id="summarize-text"
          className="focus-field h-32 w-full resize-y rounded-xl border border-input bg-card p-3 text-base text-foreground placeholder:text-text-secondary sm:text-sm"
          placeholder="Paste text here or type chapter name like 'Acid Bases and Salts'…"
        />
        <Button type="button" disabled className="bg-warning text-warning-soft shadow-warning/20 hover:bg-warning">
          <Lightbulb aria-hidden className="h-4 w-4" />
          <SoonLabel>Generate 2-Min Summary</SoonLabel>
        </Button>
      </section>

      <section
        aria-labelledby="summary-example"
        className="space-y-3 rounded-2xl border border-warning/30 bg-warning-soft/60 p-5 elev-1 sm:p-6"
      >
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-warning/25 pb-2">
          <h2 id="summary-example" className="flex items-center gap-2 text-sm font-bold text-foreground">
            {SUMMARY_EXAMPLE.title} <PreviewBadge />
          </h2>
          <span className="rounded-md bg-warning-soft px-2 py-0.5 text-2xs font-semibold text-warning">
            {SUMMARY_EXAMPLE.readTime}
          </span>
        </div>
        <ul className="list-inside list-disc space-y-2 text-xs leading-relaxed text-foreground">
          {SUMMARY_EXAMPLE.points.map((point) => (
            <li key={point.term}>
              <strong>{point.term}:</strong> {point.text}
            </li>
          ))}
        </ul>
      </section>
    </ToolPage>
  );
}
