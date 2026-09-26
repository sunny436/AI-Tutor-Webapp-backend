"use client";

import { Skeleton, SkeletonGroup } from "@v1/ui/skeleton";
import { useCallback, useEffect, useRef, useState } from "react";

import { describeError } from "@/lib/api/errors";
import { getLearningPreferences, previewTutor, updateLearningPreferences } from "@/lib/api/learning";
import type { LearningPreferenceField, LearningPreferenceValues, LearningPreferences } from "@/lib/api/types";
import { LEARNING_FIELDS, PREFERENCES, TUTOR_FIELDS } from "./learning-labels";
import { ChoiceGroup, SectionHeading, SettingsCard } from "./primitives";
import { useAutoSaver } from "./use-auto-saver";

function preferenceChanges(set: Partial<LearningPreferences>): Partial<LearningPreferenceValues> {
  const changes: Partial<LearningPreferenceValues> = {};
  for (const field of [...LEARNING_FIELDS, ...TUTOR_FIELDS]) {
    if (set[field] !== undefined) (changes as Record<string, unknown>)[field] = set[field];
  }
  return changes;
}

function usePreferences(onSaved?: () => void) {
  return useAutoSaver<LearningPreferences>({
    load: getLearningPreferences,
    save: (version, set) => updateLearningPreferences({ version, set: preferenceChanges(set) }),
    onSaved,
  });
}

function Choices({
  fields,
  value,
  change,
}: {
  fields: readonly LearningPreferenceField[];
  value: LearningPreferences;
  change: (changes: Partial<LearningPreferences>) => void;
}) {
  return (
    <>
      {fields.map((field) => {
        const info = PREFERENCES[field];
        const options = Object.entries(info.options) as [string, string][];
        return (
          <ChoiceGroup<string>
            key={field}
            legend={info.label}
            description={info.description}
            value={value[field]}
            options={options.map(([option, label]) => ({ value: option, label }))}
            onChange={(option) => change({ [field]: option } as Partial<LearningPreferences>)}
          />
        );
      })}
    </>
  );
}

function LoadFailed({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <SettingsCard title="Couldn't load your preferences">
      <p className="text-sm text-text-secondary">{describeError(error).message}</p>
      <button
        type="button"
        onClick={retry}
        className="focus-ring self-start rounded text-sm font-medium text-brand underline underline-offset-2"
      >
        Try again
      </button>
    </SettingsCard>
  );
}

const NEUTRAL_NOTE = "No preference leaves it to the tutor. Changes are saved as you make them.";

export function LearningSection() {
  const { value, change, loadError, retry } = usePreferences();
  return (
    <>
      <SectionHeading title="Learning Preferences" description="How you like to learn. The tutor follows these unless you ask it for something else in a chat." />
      {loadError ? (
        <LoadFailed error={loadError} retry={retry} />
      ) : !value ? (
        <SkeletonGroup label="Loading your preferences">
          <Skeleton className="h-96 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <SettingsCard title="How you learn" description={NEUTRAL_NOTE}>
          <Choices fields={LEARNING_FIELDS} value={value} change={change} />
        </SettingsCard>
      )}
    </>
  );
}

/**
 * "What your tutor is told": the API's own preview (POST /v1/learning/tutor-preview), built by
 * the same function the chat uses, so it cannot differ from a real conversation. Refreshed
 * after every save. It is instructions, never shown as if it were a reply.
 */
function TutorPreviewCard({ refreshKey }: { refreshKey: number }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setText((await previewTutor()).instructions);
      setError(null);
    } catch (failure) {
      setError(describeError(failure).message);
    }
  }, []);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void refresh(), refreshKey === 0 ? 0 : 300);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [refreshKey, refresh]);

  return (
    <SettingsCard
      title="What your tutor is told"
      description="Added to the tutor's standard instructions, from your Academic Profile, Learning Goals, Subjects and preferences. Your name, email and photo are never included."
    >
      {error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : text === null ? (
        <SkeletonGroup label="Loading the preview">
          <Skeleton className="h-24 w-full rounded-xl" />
        </SkeletonGroup>
      ) : text === "" ? (
        <p className="text-sm text-text-secondary">
          Nothing yet: with nothing chosen, your tutor gets only its standard instructions.
        </p>
      ) : (
        <pre
          aria-live="polite"
          className="max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-border bg-surface p-3.5 font-sans text-sm leading-relaxed text-foreground"
        >
          {text}
        </pre>
      )}
    </SettingsCard>
  );
}

export function TutorSection() {
  const [saves, setSaves] = useState(0);
  const { value, change, loadError, retry } = usePreferences(() => setSaves((count) => count + 1));
  return (
    <>
      <SectionHeading title="AI Tutor" description="How your tutor talks to you and works through problems with you." />
      {loadError ? (
        <LoadFailed error={loadError} retry={retry} />
      ) : !value ? (
        <SkeletonGroup label="Loading your tutor settings">
          <Skeleton className="h-96 w-full rounded-2xl" />
        </SkeletonGroup>
      ) : (
        <div className="flex flex-col gap-4">
          <SettingsCard title="Your tutor" description={NEUTRAL_NOTE}>
            <Choices fields={TUTOR_FIELDS} value={value} change={change} />
          </SettingsCard>
          <TutorPreviewCard refreshKey={saves} />
        </div>
      )}
    </>
  );
}
