import { Button } from "@v1/ui/button";
import { Camera, CheckCircle2, UploadCloud } from "lucide-react";

import { PreviewBadge } from "@/components/preview-badge";
import { HOMEWORK_EXAMPLE } from "./demo-data";
import { SoonLabel, ToolPage } from "./tool-page";

/** Homework Helper (preview): where a photo would go, and one worked example. */
export function HomeworkView() {
  return (
    <ToolPage label="Homework Helper">
      <section className="rounded-3xl border-2 border-dashed border-brand/30 bg-brand-soft/40 p-6 text-center sm:p-8">
        <span aria-hidden className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-brand-soft text-brand">
          <UploadCloud className="h-8 w-8" />
        </span>
        <h2 className="mb-1 text-lg font-bold text-foreground">Upload Homework Photo or Worksheet</h2>
        <p className="mx-auto mb-5 max-w-sm text-xs text-text-secondary">
          Take a snap of your NCERT Math problem, Physics numerical, or Chemistry reaction for step-by-step solutions.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Button type="button" disabled>
            <SoonLabel>Select Image / PDF</SoonLabel>
          </Button>
          <Button type="button" variant="outline" disabled>
            <Camera aria-hidden className="h-4 w-4" />
            <SoonLabel>Use Mobile Camera</SoonLabel>
          </Button>
        </div>
      </section>

      <section aria-labelledby="homework-example" className="space-y-4 rounded-2xl border border-border bg-card p-5 elev-1 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
          <h2 id="homework-example" className="flex items-center gap-2">
            <span className="flex items-center gap-1 rounded-full bg-success-soft px-3 py-1 text-xs font-bold text-success">
              <CheckCircle2 aria-hidden className="h-3.5 w-3.5" /> Solved Step-by-Step
            </span>
            <PreviewBadge />
          </h2>
          <span className="text-xs text-text-secondary">Source: {HOMEWORK_EXAMPLE.source}</span>
        </div>

        <div className="rounded-xl border border-border bg-surface p-4 font-mono text-sm text-foreground">
          <span className="mb-1 block font-sans text-xs font-bold text-text-secondary">Detected Question:</span>
          {`“${HOMEWORK_EXAMPLE.question}”`}
        </div>

        <ol className="space-y-3">
          {HOMEWORK_EXAMPLE.steps.map((step) => (
            <li key={step.title} className="rounded-xl border border-brand/15 bg-brand-soft/50 p-3">
              <span className="mb-1 block text-xs font-bold text-brand">{step.title}</span>
              {step.note && <p className="text-xs text-text-secondary">{step.note}</p>}
              {step.work.map((line, index) => (
                <p
                  key={line}
                  className={`mt-1 font-mono text-xs text-foreground ${index === step.work.length - 1 && step.work.length > 1 ? "font-bold" : ""}`}
                >
                  {line}
                </p>
              ))}
            </li>
          ))}
        </ol>

        <div className="rounded-xl border border-success/30 bg-success-soft p-3">
          <span className="mb-1 block text-xs font-bold text-success">Final Answer:</span>
          <p className="text-xs font-bold text-foreground">{HOMEWORK_EXAMPLE.answer}</p>
        </div>
      </section>
    </ToolPage>
  );
}
