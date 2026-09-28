"use client";

import { Button } from "@v1/ui/button";
import { cn } from "@v1/ui/utils";
import { ArrowRight, BookMarked, Check } from "lucide-react";
import { useState } from "react";

import { COURSE_OVERVIEW, SYLLABUS } from "./demo-data";
import { SoonLabel, ToolPage } from "./tool-page";

/** My Courses (preview): the syllabus overview, a course picker and its chapters. */
export function CoursesView() {
  const [selectedId, setSelectedId] = useState(SYLLABUS[0]?.id);
  const selected = SYLLABUS.find((course) => course.id === selectedId) ?? SYLLABUS[0];
  if (!selected) return null;

  return (
    <ToolPage label="My Courses" width="wide">
      <section className="bg-hero-deep relative overflow-hidden rounded-3xl p-6 text-hero-foreground elev-2 sm:p-8">
        <div className="relative max-w-2xl">
          <span className="mb-3 inline-block rounded-full bg-hero-foreground/20 px-3 py-1 text-xs font-semibold uppercase tracking-wider">
            {COURSE_OVERVIEW.tag}
          </span>
          <h2 className="mb-2 font-display text-2xl font-black sm:text-3xl">{COURSE_OVERVIEW.title}</h2>
          <p className="mb-5 text-sm text-hero-muted">{COURSE_OVERVIEW.lead}</p>
          <dl className="flex flex-wrap gap-3">
            <div className="rounded-xl border border-hero-foreground/15 bg-hero-foreground/10 px-4 py-2 text-xs">
              <dt className="text-hero-muted">Overall Completion</dt>
              <dd className="text-lg font-bold">{COURSE_OVERVIEW.completion}</dd>
            </div>
            <div className="rounded-xl border border-hero-foreground/15 bg-hero-foreground/10 px-4 py-2 text-xs">
              <dt className="text-hero-muted">Next Test</dt>
              <dd className="text-lg font-bold">{COURSE_OVERVIEW.nextTest}</dd>
            </div>
          </dl>
        </div>
      </section>

      <ul aria-label="Courses" className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {SYLLABUS.map((course) => {
          const current = course.id === selected.id;
          return (
            <li key={course.id}>
              <button
                type="button"
                aria-pressed={current}
                onClick={() => setSelectedId(course.id)}
                className={cn(
                  "focus-ring w-full rounded-2xl border bg-card p-5 text-left transition-[border-color,box-shadow]",
                  current ? "border-brand elev-2 ring-2 ring-brand/20" : "border-border elev-1 hover:border-brand/30",
                )}
              >
                <span className="mb-3 flex items-center justify-between">
                  <span className="rounded-lg bg-brand-soft px-2.5 py-1 text-xs font-bold text-brand">{course.board}</span>
                  <span className="text-xs font-semibold text-text-secondary">{course.grade}</span>
                </span>
                <span className="mb-3 block text-base font-bold text-foreground">{course.title}</span>
                <span className="flex justify-between text-xs font-semibold text-text-secondary">
                  <span>Progress</span>
                  <span>{course.progress}%</span>
                </span>
                <span
                  role="progressbar"
                  aria-label={`${course.title} progress`}
                  aria-valuenow={course.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="mt-1.5 block h-2 w-full overflow-hidden rounded-full bg-surface-2"
                >
                  <span className="block h-full rounded-full bg-brand" style={{ width: `${course.progress}%` }} />
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <section className="rounded-2xl border border-border bg-card p-5 elev-1 sm:p-6">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
          <div>
            <h3 className="text-lg font-bold text-foreground">{selected.title} Chapters</h3>
            <p className="text-xs text-text-secondary">Select a chapter to read summary or solve textbook doubts</p>
          </div>
          <Button type="button" variant="secondary" size="sm" disabled>
            <BookMarked aria-hidden className="h-4 w-4 text-brand" />
            <SoonLabel>Syllabus PDF</SoonLabel>
          </Button>
        </div>

        <ol className="space-y-3">
          {selected.chapters.map((chapter, index) => (
            <li
              key={chapter.id}
              className={cn(
                "flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4",
                chapter.active ? "border-brand/30 bg-brand-soft/60 ring-1 ring-brand/20" : "border-border bg-surface",
              )}
            >
              <div className="flex min-w-0 items-center gap-3.5">
                <span
                  className={cn(
                    "grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-bold",
                    chapter.completed
                      ? "bg-success text-card"
                      : chapter.active
                        ? "bg-brand text-brand-foreground"
                        : "bg-surface-2 text-text-secondary",
                  )}
                >
                  {chapter.completed ? <Check aria-hidden className="h-4 w-4" /> : index + 1}
                  <span className="sr-only">
                    {chapter.completed ? "Completed" : chapter.active ? "In progress" : "Not started"}
                  </span>
                </span>
                <div className="min-w-0">
                  <h4 className="text-sm font-bold text-foreground">{chapter.title}</h4>
                  <p className="text-xs text-text-secondary">{chapter.questions} Practice Questions Available</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" variant="outline" size="sm" disabled>
                  <SoonLabel>Study Notes</SoonLabel>
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled
                  aria-label={`Open ${chapter.title} (coming soon)`}
                  className="w-9 px-0"
                >
                  <ArrowRight aria-hidden className="h-4 w-4" />
                </Button>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </ToolPage>
  );
}
