"use client";

import { Button } from "@v1/ui/button";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ApiError, describeError } from "@/lib/api/errors";
import type { CatalogEntry, LearnerProfile, LearnerProfileField, LearnerProfileValues } from "@/lib/api/types";
import { ProfileConflict, catalogOptions, useLearnerProfile } from "./learning-data";
import { editFor, hasChanges } from "./learning-model";
import { Field } from "./primitives";
import { useUnsavedChanges } from "./use-unsaved-changes";

export type ProfileDraft = { [K in LearnerProfileField]?: LearnerProfileValues[K] | null };

function pick(profile: LearnerProfile, fields: readonly LearnerProfileField[]): ProfileDraft {
  const values: ProfileDraft = {};
  for (const field of fields) (values as Record<string, unknown>)[field] = profile[field];
  return values;
}

/**
 * One form over some of the learner profile's fields (Academic Profile, Learning Goals). Saves
 * only what changed as one versioned edit; keeps the user's edit on a conflict; blocks double
 * submits; warns before leaving unsaved; shows the API's field errors next to their fields.
 */
export function useProfileForm(fields: readonly LearnerProfileField[], savedMessage: string) {
  const { profile, error, save, retry } = useLearnerProfile();
  const base = useMemo(() => (profile ? pick(profile, fields) : null), [profile, fields]);
  const [draft, setDraft] = useState<ProfileDraft | null>(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [invalid, setInvalid] = useState<Set<string>>(new Set());
  const edit = base && draft ? editFor<ProfileDraft>(base, draft, fields) : null;
  const dirty = edit ? hasChanges(edit) : false;
  useUnsavedChanges(dirty);

  // The loaded (or conflicting) profile becomes the form, unless the user has edits in it.
  // Follows `base` only while the form is clean.
  useEffect(() => {
    if (base && (!draft || !dirty)) setDraft(base);
  }, [base]);

  const change = (values: ProfileDraft) => {
    setDraft((current) => ({ ...current, ...values }));
    setInvalid((current) => {
      const next = new Set(current);
      for (const key of Object.keys(values)) next.delete(key);
      return next;
    });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending || !edit || !dirty) return;
    setPending(true);
    setNotice(null);
    setInvalid(new Set());
    try {
      const saved = await save(edit.set as Partial<LearnerProfileValues>, edit.reset);
      setDraft(pick(saved, fields));
      toast.success(savedMessage);
    } catch (failure) {
      if (failure instanceof ProfileConflict) {
        setNotice("This was just changed somewhere else. Your edits are still here: check them and save again.");
      } else if (failure instanceof ApiError && failure.fields?.length) {
        const names = failure.fields.map((entry) => entry.field.replace(/^set\./, "").split(".")[0] ?? "");
        setInvalid(new Set(names));
        if (!names.some((name) => fields.includes(name as LearnerProfileField))) toast.error(describeError(failure).message);
      } else {
        toast.error(describeError(failure).message);
      }
    } finally {
      setPending(false);
    }
  };

  return {
    draft,
    loadError: error,
    retry,
    change,
    submit,
    reset: () => base && setDraft(base),
    dirty,
    pending,
    notice,
    invalid: (field: LearnerProfileField) => invalid.has(field),
  };
}

export function SaveFooter({ dirty, pending, onCancel }: { dirty: boolean; pending: boolean; onCancel: () => void }) {
  return (
    <>
      {dirty && (
        <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
      )}
      <Button type="submit" size="sm" disabled={pending || !dirty}>
        {pending ? "Saving…" : "Save"}
      </Button>
    </>
  );
}

const selectClass = "focus-field h-10 w-full rounded-xl border border-input bg-card px-3 text-base sm:max-w-[20rem] sm:text-sm";

/** A catalog-driven choice. A deprecated value is kept and shown as such, never offered anew. */
export function CatalogSelect({
  label,
  hint,
  entries,
  value,
  onChange,
  error,
}: {
  label: string;
  hint?: string;
  entries: readonly CatalogEntry[];
  value: string | null | undefined;
  onChange: (value: string | null) => void;
  error?: string | null;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(props) => (
        <select {...props} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)} className={selectClass}>
          <option value="">Not set</option>
          {catalogOptions(entries, value).map((entry) => (
            <option key={entry.code} value={entry.code}>
              {entry.deprecated ? `${entry.name} (no longer offered)` : entry.name}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

export { selectClass };
