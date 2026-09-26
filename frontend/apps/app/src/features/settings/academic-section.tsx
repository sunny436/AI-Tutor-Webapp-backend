"use client";

import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";

import { describeError } from "@/lib/api/errors";
import type { LearnerProfileField } from "@/lib/api/types";
import { useCatalog } from "./learning-data";
import { Notice, SectionHeading, SettingsCard } from "./primitives";
import { CatalogSelect, SaveFooter, useProfileForm } from "./profile-form";

const FIELDS = ["grade", "board", "boardState", "medium", "academicYear"] as const satisfies readonly LearnerProfileField[];
const CHECK = "Choose one from the list.";

export function AcademicSection() {
  const { catalog, error: catalogError, retry: retryCatalog } = useCatalog();
  const form = useProfileForm(FIELDS, "Academic profile saved.");
  const loadError = catalogError ?? form.loadError;

  return (
    <>
      <SectionHeading
        title="Academic Profile"
        description="Where and what you study. The tutor uses it to pitch explanations and examples at your level."
      />
      {loadError ? (
        <SettingsCard title="Couldn't load your academic profile">
          <p className="text-sm text-text-secondary">{describeError(loadError).message}</p>
          <button
            type="button"
            onClick={() => (catalogError ? retryCatalog() : form.retry())}
            className="focus-ring self-start rounded text-sm font-medium text-brand underline underline-offset-2"
          >
            Try again
          </button>
        </SettingsCard>
      ) : !catalog || !form.draft ? (
        <SkeletonGroup label="Loading your academic profile">
          <Skeleton className="h-80 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <form onSubmit={form.submit}>
          <SettingsCard
            title="Your studies"
            description="Leave anything you'd rather not say as Not set."
            footer={<SaveFooter dirty={form.dirty} pending={form.pending} onCancel={form.reset} />}
          >
            {form.notice && <Notice tone="warning">{form.notice}</Notice>}
            <CatalogSelect
              label="Class"
              entries={catalog.grades}
              value={form.draft.grade}
              onChange={(grade) => form.change({ grade })}
              error={form.invalid("grade") ? CHECK : null}
            />
            <CatalogSelect
              label="Board"
              entries={catalog.boards}
              value={form.draft.board}
              // A state is only meaningful for a state board: leaving one clears it.
              onChange={(board) => form.change(board === "state" ? { board } : { board, boardState: null })}
              error={form.invalid("board") ? CHECK : null}
            />
            {form.draft.board === "state" && (
              <CatalogSelect
                label="State"
                entries={catalog.boardStates}
                value={form.draft.boardState}
                onChange={(boardState) => form.change({ boardState })}
                error={form.invalid("boardState") ? CHECK : null}
              />
            )}
            <CatalogSelect
              label="Medium of instruction"
              hint="The language you're taught in at school."
              entries={catalog.mediums}
              value={form.draft.medium}
              onChange={(medium) => form.change({ medium })}
              error={form.invalid("medium") ? CHECK : null}
            />
            <CatalogSelect
              label="Academic year"
              entries={catalog.academicYears}
              value={form.draft.academicYear}
              onChange={(academicYear) => form.change({ academicYear })}
              error={form.invalid("academicYear") ? CHECK : null}
            />
          </SettingsCard>
        </form>
      )}
    </>
  );
}
