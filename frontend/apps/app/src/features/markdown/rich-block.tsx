"use client";

import { Component, type ComponentType, type ReactNode, Suspense, lazy, useCallback, useContext, useState } from "react";

import { LiveContext } from "./context";

/**
 * What every widget gets: its fence's source, and a way to give up (the code block shows instead,
 * under `note` when the widget says why).
 */
export type WidgetProps = { source: string; onError: (note?: string) => void };

const WIDGETS = new Map<string, { label: string; load: ComponentType<WidgetProps> }>([
  ["mermaid", { label: "diagram", load: lazy(() => import("./widgets/mermaid-diagram")) }],
  ["chart", { label: "chart", load: lazy(() => import("./widgets/chart-view")) }],
  ["mcq", { label: "question", load: lazy(() => import("./widgets/quiz").then((m) => ({ default: m.McqBlock }))) }],
  ["quiz", { label: "quiz", load: lazy(() => import("./widgets/quiz").then((m) => ({ default: m.QuizBlock }))) }],
  ["question-bank", { label: "your test", load: lazy(() => import("./widgets/quiz").then((m) => ({ default: m.BankBlock }))) }],
  ["flashcards", { label: "flashcards", load: lazy(() => import("./widgets/flashcards")) }],
  ["fill-blank", { label: "exercise", load: lazy(() => import("./widgets/fill-blank")) }],
  ["graph", { label: "graph", load: lazy(() => import("./widgets/math-graph")) }],
  ["diagram", { label: "diagram", load: lazy(() => import("./widgets/concept-diagram")) }],
]);

export function isRichLanguage(language: string | null): language is string {
  return language !== null && WIDGETS.has(language);
}

class Boundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Placeholder({ label }: { label: string }) {
  return (
    <div
      role="status"
      className="my-3 flex h-24 items-center justify-center rounded-xl border border-border bg-study-card text-sm text-text-secondary motion-safe:animate-pulse"
    >
      Preparing {label}…
    </div>
  );
}

/**
 * A fenced block the tutor draws instead of printing: a diagram, a chart, a practice widget.
 * Loaded only when a reply has one (each library is its own chunk). While the reply is still
 * writing the block, a quiet placeholder; if the source cannot be drawn, the code block it came
 * from, so nothing the tutor wrote is ever lost. Keyed by its source where it is used, so new
 * source always gets a fresh try.
 */
export function RichBlock({ language, source, fallback }: { language: string; source: string; fallback: ReactNode }) {
  const live = useContext(LiveContext);
  const [failed, setFailed] = useState<string | null>(null);
  const fail = useCallback((note?: string) => setFailed(note ?? ""), []);
  const widget = WIDGETS.get(language);
  if (!widget) return fallback;
  if (live) return <Placeholder label={widget.label} />;
  const shown = (
    <div>
      <p className="mb-[-0.25rem] mt-3 text-2xs text-text-secondary">
        {failed || `This ${widget.label} couldn't be shown; here is its source.`}
      </p>
      {fallback}
    </div>
  );
  if (failed !== null) return shown;
  const Widget = widget.load;
  return (
    <Boundary fallback={shown}>
      <Suspense fallback={<Placeholder label={widget.label} />}>
        <Widget source={source} onError={fail} />
      </Suspense>
    </Boundary>
  );
}
